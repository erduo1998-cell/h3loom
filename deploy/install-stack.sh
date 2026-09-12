#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly DATA_ROOT=/root/autodl-tmp
readonly STACK_ROOT="$DATA_ROOT/h3-stack"
readonly ENV_ROOT="$STACK_ROOT/env"
readonly COMFY_ROOT="$STACK_ROOT/ComfyUI"
readonly RECEIPT_ROOT="$STACK_ROOT/receipts"
readonly INCOMING_ROOT="$STACK_ROOT/incoming"
readonly COMFY_COMMIT=72865f4f27eaf5396f8f36370e0a2be3a9a090ee
readonly KJNODES_COMMIT=3f20054214fec9f9234fd3841ae6f1e4287948f6
readonly RTX_NODES_COMMIT=892515e3eb9a4920a131a502a047e47adca9eb0d
readonly H3_EASY_ARCHIVE=h3-easy-33b6a795ea8f53354eb6b7854a731be49ef24a4e.tar.gz
readonly H3_EASY_SHA256=c942f384488e486d3d2b2e86cd2494aa479ac87b6b9e11879ae54b7975ae1a7f
readonly H3_KEYFRAMES_COMMIT=9bce864b7df056a2822e4af593de17ef199ebcdc
readonly H3_KEYFRAMES_INIT_SHA256=f0812349809276f0fa32987e9abea45ca0b7b48a6388808abf5bfb4dd29c8dd8
readonly H3_KEYFRAMES_NODE_SHA256=5bd69ba55a2b243bbd5a1947d8822e135128ebeaf10a921f930cd33d15b62d3a
readonly H3_KEYFRAMES_PATCH_SHA256=91fbafb062402c83c9536b4776adaa075ee3038b875ba89180460708ed3b9737
readonly H3_KEYFRAMES_LICENSE_SHA256=cb072345070bdad3c577c28c0d83eff742524ae90c0d0721ebe614169c7378ec
readonly H3_KEYFRAMES_SOURCE_SHA256=42ceea155c4d26440011e2ab0720be3b562f420cf5c62d96876e9650cc2f6dd6
# NVIDIA publishes the CPython 3.12 Linux wheel on its own index.  The package
# with the same name on ordinary PyPI is a source bootstrap that requires the
# unavailable ``wheel-stub`` build dependency, so it must never be selected.
readonly NVIDIA_VFX_WHEEL_URL=https://pypi.nvidia.com/nvidia-vfx/nvidia_vfx-0.1.0.1-cp312-abi3-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl
readonly NVIDIA_VFX_WHEEL_SHA256=e51d9e6faa68466e45b83be7928321af4b0c561c7c5536a8cb2b7e6aba25f905
readonly NVIDIA_VFX_WHEEL=nvidia_vfx-0.1.0.1-cp312-abi3-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl

die() {
  printf 'install-stack: %s\n' "$*" >&2
  exit 1
}

apply_approved_comfy_patches() (
  # Build the approved result in a disposable index without changing HEAD or
  # the real index. Accept only original or exactly patched file bytes.
  local patch_index patch_file target original approved actual
  local pending=()
  patch_index=$(mktemp)
  trap 'rm -f "$patch_index"' EXIT
  rm -f "$patch_index"
  export GIT_INDEX_FILE="$patch_index"
  git -C "$COMFY_ROOT" read-tree "$COMFY_COMMIT"
  for patch_file in loadimage-recursive.patch loadmedia-recursive.patch; do
    [[ -f "$INCOMING_ROOT/$patch_file" ]] || die "missing approved patch: $patch_file"
    git -C "$COMFY_ROOT" apply --cached "$INCOMING_ROOT/$patch_file" ||
      die "patch does not match frozen ComfyUI: $patch_file"
  done
  for target in nodes.py comfy_extras/nodes_video.py comfy_extras/nodes_audio.py; do
    original=$(git -C "$COMFY_ROOT" rev-parse "$COMFY_COMMIT:$target")
    approved=$(git -C "$COMFY_ROOT" rev-parse ":$target")
    actual=$(git -C "$COMFY_ROOT" hash-object -- "$target")
    [[ "$actual" == "$original" || "$actual" == "$approved" ]] ||
      die "unexpected ComfyUI changes: $target"
  done
  # Each patch is either untouched or already applied. A partial multi-file
  # patch is an interrupted/unknown state and must be inspected, not guessed.
  for patch_file in loadimage-recursive.patch loadmedia-recursive.patch; do
    if git -C "$COMFY_ROOT" apply --check "$INCOMING_ROOT/$patch_file" 2>/dev/null; then
      pending+=("$patch_file")
    elif ! git -C "$COMFY_ROOT" apply --reverse --check "$INCOMING_ROOT/$patch_file" 2>/dev/null; then
      die "partially applied ComfyUI patch: $patch_file"
    fi
  done
  for patch_file in "${pending[@]}"; do
    git -C "$COMFY_ROOT" apply "$INCOMING_ROOT/$patch_file"
  done
)

[[ -d "$DATA_ROOT" ]] || die "$DATA_ROOT is missing"
mount_target=$(findmnt -n -o TARGET -T "$DATA_ROOT")
[[ "$mount_target" == "$DATA_ROOT" ]] || die "$DATA_ROOT is not a dedicated mount"

gpu_name=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -n 1)
gpu_total_mib=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -n 1 | tr -d ' ')
[[ "$gpu_name" == *"RTX PRO 6000 Blackwell Server Edition"* ]] || die "unexpected GPU: $gpu_name"
(( gpu_total_mib >= 90000 )) || die "GPU VRAM below 90000 MiB: $gpu_total_mib"

memory_limit=$(cat /sys/fs/cgroup/memory.max 2>/dev/null || printf 'max')
[[ "$memory_limit" != max ]] || die "cgroup memory limit is unknown"
(( memory_limit >= 128849018880 )) || die "cgroup memory below 120 GiB: $memory_limit"

free_bytes=$(df -B1 --output=avail "$DATA_ROOT" | tail -n 1 | tr -d ' ')
(( free_bytes >= 320000000000 )) || die "persistent disk free space below 320 GB: $free_bytes"

mkdir -p "$STACK_ROOT" "$RECEIPT_ROOT" "$INCOMING_ROOT" "$STACK_ROOT/staging"
export CONDA_PKGS_DIRS="$DATA_ROOT/conda-pkgs"
export PIP_CACHE_DIR="$DATA_ROOT/pip-cache"
export HF_HOME="$DATA_ROOT/hf-cache"
mkdir -p "$CONDA_PKGS_DIRS" "$PIP_CACHE_DIR" "$HF_HOME"

[[ -f "$INCOMING_ROOT/cloud-requirements.txt" ]] || die "missing cloud-requirements.txt"
export PIP_CONSTRAINT="$INCOMING_ROOT/cloud-requirements.txt"
source /root/miniconda3/etc/profile.d/conda.sh
if [[ ! -x "$ENV_ROOT/bin/python" ]]; then
  conda create --prefix "$ENV_ROOT" --override-channels -c conda-forge python=3.12 pip -y
fi

# The base AutoDL image does not guarantee ffmpeg/ffprobe.  Pin both tools in
# the same persistent environment used by Comfy and the benchmark runners so
# video encoding and receipt verification cannot depend on ephemeral /usr/bin.
conda install --prefix "$ENV_ROOT" --override-channels -c conda-forge "ffmpeg=7" -y
export PATH="$ENV_ROOT/bin:$PATH"
"$ENV_ROOT/bin/ffmpeg" -version >/dev/null
"$ENV_ROOT/bin/ffprobe" -version >/dev/null

"$ENV_ROOT/bin/python" -m pip install setuptools==78.1.0 wheel==0.48.0
"$ENV_ROOT/bin/python" -m pip install \
  torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 \
  --index-url https://download.pytorch.org/whl/cu130

if [[ ! -d "$COMFY_ROOT/.git" ]]; then
  git clone --filter=blob:none https://github.com/Comfy-Org/ComfyUI.git "$COMFY_ROOT"
fi
git -C "$COMFY_ROOT" fetch --depth 1 origin "$COMFY_COMMIT"
git -C "$COMFY_ROOT" checkout --detach "$COMFY_COMMIT"
apply_approved_comfy_patches
"$ENV_ROOT/bin/python" -m pip install -r "$COMFY_ROOT/requirements.txt"

install_git_node() {
  local repository=$1
  local commit=$2
  local target=$3
  if [[ ! -d "$target/.git" ]]; then
    git clone --filter=blob:none "$repository" "$target"
  fi
  git -C "$target" fetch --depth 1 origin "$commit"
  git -C "$target" checkout --detach "$commit"
  if [[ -f "$target/requirements.txt" ]]; then
    "$ENV_ROOT/bin/python" -m pip install -r "$target/requirements.txt"
  fi
}

install_git_node \
  https://github.com/kijai/ComfyUI-KJNodes.git \
  "$KJNODES_COMMIT" \
  "$COMFY_ROOT/custom_nodes/ComfyUI-KJNodes"

# Install the vendor wheel before this node's requirements file.  Once the
# exact version is installed, pip considers the unpinned ``nvidia-vfx`` line
# satisfied and does not fall back to PyPI's broken source bootstrap.
vfx_wheel="$INCOMING_ROOT/$NVIDIA_VFX_WHEEL"
if [[ ! -f "$vfx_wheel" ]]; then
  curl --fail --location --retry 5 --retry-all-errors --connect-timeout 30 \
    --output "$vfx_wheel.part" "$NVIDIA_VFX_WHEEL_URL"
  printf '%s  %s\n' "$NVIDIA_VFX_WHEEL_SHA256" "$vfx_wheel.part" | sha256sum -c -
  mv "$vfx_wheel.part" "$vfx_wheel"
fi
printf '%s  %s\n' "$NVIDIA_VFX_WHEEL_SHA256" "$vfx_wheel" | sha256sum -c -
"$ENV_ROOT/bin/python" -m pip install "$vfx_wheel"

install_git_node \
  https://github.com/Comfy-Org/Nvidia_RTX_Nodes_ComfyUI.git \
  "$RTX_NODES_COMMIT" \
  "$COMFY_ROOT/custom_nodes/Nvidia_RTX_Nodes_ComfyUI"

bundle="$INCOMING_ROOT/$H3_EASY_ARCHIVE"
[[ -f "$bundle" ]] || die "missing uploaded H3 Easy bundle: $bundle"
printf '%s  %s\n' "$H3_EASY_SHA256" "$bundle" | sha256sum -c -

h3_stage=$(mktemp -d "$STACK_ROOT/staging/h3-easy.XXXXXX")
tar -xzf "$bundle" -C "$h3_stage"
h3_bundle_root="$h3_stage/h3-easy-33b6a795ea8f53354eb6b7854a731be49ef24a4e"
"$h3_bundle_root/scripts/verify_bundle.sh" \
  "$h3_bundle_root/custom_nodes/ComfyUI-MiniMaxH3-Easy"

h3_target="$COMFY_ROOT/custom_nodes/ComfyUI-MiniMaxH3-Easy"
if [[ -e "$h3_target" ]]; then
  h3_backup="$STACK_ROOT/backups/h3-easy-$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$(dirname "$h3_backup")"
  mv "$h3_target" "$h3_backup"
fi
mv "$h3_bundle_root/custom_nodes/ComfyUI-MiniMaxH3-Easy" "$h3_target"
rm -rf "$h3_stage"

h3_keyframes_source="$INCOMING_ROOT/h3-keyframes-only"
[[ -d "$h3_keyframes_source" ]] || die "missing H3Keyframes vendor directory"
printf '%s  %s\n' "$H3_KEYFRAMES_INIT_SHA256" "$h3_keyframes_source/__init__.py" | sha256sum -c -
printf '%s  %s\n' "$H3_KEYFRAMES_NODE_SHA256" "$h3_keyframes_source/h3_keyframes.py" | sha256sum -c -
printf '%s  %s\n' "$H3_KEYFRAMES_PATCH_SHA256" "$h3_keyframes_source/h3_interior_patch.py" | sha256sum -c -
printf '%s  %s\n' "$H3_KEYFRAMES_LICENSE_SHA256" "$h3_keyframes_source/LICENSE" | sha256sum -c -
printf '%s  %s\n' "$H3_KEYFRAMES_SOURCE_SHA256" "$h3_keyframes_source/SOURCE.json" | sha256sum -c -
h3_keyframes_stage=$(mktemp -d "$STACK_ROOT/staging/h3-keyframes.XXXXXX")
install -m 600 "$h3_keyframes_source/__init__.py" "$h3_keyframes_stage/__init__.py"
install -m 600 "$h3_keyframes_source/h3_keyframes.py" "$h3_keyframes_stage/h3_keyframes.py"
install -m 600 "$h3_keyframes_source/h3_interior_patch.py" "$h3_keyframes_stage/h3_interior_patch.py"
install -m 600 "$h3_keyframes_source/LICENSE" "$h3_keyframes_stage/LICENSE"
install -m 600 "$h3_keyframes_source/SOURCE.json" "$h3_keyframes_stage/SOURCE.json"
h3_keyframes_target="$COMFY_ROOT/custom_nodes/h3-keyframes-only"
if [[ -e "$h3_keyframes_target" ]]; then
  h3_keyframes_backup="$STACK_ROOT/backups/h3-keyframes-$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$(dirname "$h3_keyframes_backup")"
  mv "$h3_keyframes_target" "$h3_keyframes_backup"
fi
mv "$h3_keyframes_stage" "$h3_keyframes_target"
# None of the frozen ComfyUI/node requirements installs the production Sage
# implementation; pin it explicitly after node dependencies have been resolved.
"$ENV_ROOT/bin/python" -m pip install -r "$INCOMING_ROOT/cloud-requirements.txt"
"$ENV_ROOT/bin/python" -m pip check

"$ENV_ROOT/bin/python" - <<'PY'
import json
import torch
import torchaudio
import comfy_kitchen
import nvvfx

if not torch.cuda.is_available():
    raise SystemExit("CUDA unavailable")
if not torch.cuda.is_bf16_supported():
    raise SystemExit("BF16 unsupported")
p = torch.cuda.get_device_properties(0)
a = torch.randn((2048, 2048), device="cuda", dtype=torch.bfloat16)
b = a @ a
torch.cuda.synchronize()
print(json.dumps({
    "torch": torch.__version__,
    "cuda_runtime": torch.version.cuda,
    "gpu": p.name,
    "compute_capability": list(torch.cuda.get_device_capability(0)),
    "arch_list": torch.cuda.get_arch_list(),
    "vram_bytes": p.total_memory,
    "bf16_supported": torch.cuda.is_bf16_supported(),
    "matmul_dtype": str(b.dtype),
    "nvidia_vfx": getattr(nvvfx, "__version__", "installed"),
}, ensure_ascii=False))
if torch.version.cuda != "13.0":
    raise SystemExit(f"unexpected CUDA runtime: {torch.version.cuda}")
if torch.cuda.get_device_capability(0) != (12, 0):
    raise SystemExit(f"unexpected compute capability: {torch.cuda.get_device_capability(0)}")
if "sm_120" not in torch.cuda.get_arch_list():
    raise SystemExit(f"sm_120 missing from torch arch list: {torch.cuda.get_arch_list()}")
PY

mkdir -p \
  "$COMFY_ROOT/models/diffusion_models" \
  "$COMFY_ROOT/models/text_encoders" \
  "$COMFY_ROOT/models/vae" \
  "$COMFY_ROOT/models/loras" \
  "$COMFY_ROOT/input" \
  "$COMFY_ROOT/output"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
{
  printf 'installed_at=%s\n' "$stamp"
  printf 'gpu_name=%s\n' "$gpu_name"
  printf 'gpu_total_mib=%s\n' "$gpu_total_mib"
  printf 'cgroup_memory_bytes=%s\n' "$memory_limit"
  printf 'comfy_commit=%s\n' "$(git -C "$COMFY_ROOT" rev-parse HEAD)"
  printf 'kjnodes_commit=%s\n' "$(git -C "$COMFY_ROOT/custom_nodes/ComfyUI-KJNodes" rev-parse HEAD)"
  printf 'rtx_nodes_commit=%s\n' "$(git -C "$COMFY_ROOT/custom_nodes/Nvidia_RTX_Nodes_ComfyUI" rev-parse HEAD)"
  printf 'h3_easy_archive_sha256=%s\n' "$H3_EASY_SHA256"
  printf 'h3_keyframes_source_commit=%s\n' "$H3_KEYFRAMES_COMMIT"
  printf 'h3_keyframes_init_sha256=%s\n' "$H3_KEYFRAMES_INIT_SHA256"
  printf 'h3_keyframes_node_sha256=%s\n' "$H3_KEYFRAMES_NODE_SHA256"
  printf 'h3_keyframes_patch_sha256=%s\n' "$H3_KEYFRAMES_PATCH_SHA256"
  printf 'h3_keyframes_license_sha256=%s\n' "$H3_KEYFRAMES_LICENSE_SHA256"
  printf 'h3_keyframes_source_sha256=%s\n' "$H3_KEYFRAMES_SOURCE_SHA256"
  printf 'nvidia_vfx_wheel_sha256=%s\n' "$NVIDIA_VFX_WHEEL_SHA256"
  printf 'ffmpeg=%s\n' "$("$ENV_ROOT/bin/ffmpeg" -version | head -n 1)"
  "$ENV_ROOT/bin/python" -m pip freeze
} > "$RECEIPT_ROOT/install-$stamp.txt"

printf 'install-stack complete: %s\n' "$STACK_ROOT"
