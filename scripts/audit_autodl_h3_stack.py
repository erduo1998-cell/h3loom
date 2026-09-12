#!/usr/bin/env python3
"""Read-only inventory and drift check for the live AutoDL MiniMax H3 stack.

The remote probe never writes to the server and never reads environment
variables, credentials, shell history, user inputs, or generated outputs.
Results are stored locally below work/stack-audits/, which is git-ignored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

from broll_video.autodl.control import AutoDLSSHEndpoint
from broll_video.autodl.credentials import AutoDLCredentials
from broll_video.autodl.ssh import AutoDLSSHClient


REMOTE_PROBE = r'''
import hashlib
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import time

HASH_MODELS = "--hash-models" in sys.argv[1:]
STACK_CANDIDATES = (
    pathlib.Path("/root/autodl-tmp/h3-stack"),
    pathlib.Path("/workspace/h3-stack"),
    pathlib.Path("/root/h3-stack"),
)
EXCLUDED_PARTS = {".git", "__pycache__", ".pytest_cache", "node_modules"}


def command(args, timeout=60):
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None



def mount_summary(stack_root):
    # SOURCE can contain a cloud container or volume identifier. Never request it.
    raw = command(["findmnt", "--json", "-o", "FSTYPE,TARGET", "-T", str(stack_root)])
    if not raw:
        return None
    try:
        filesystems = json.loads(raw)["filesystems"]
        mount = filesystems[0]
        return {key: mount.get(key) for key in ("fstype", "target")}
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return None


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(8 * 1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def safe_relative(path, root):
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def sanitized_text(value):
    value = re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1REDACTED@", value)
    value = re.sub(
        r"(?i)(token|access_token|password|secret)=([^&\s]+)",
        r"\1=REDACTED",
        value,
    )
    return value


def git_value(repo, *args):
    return command(["git", "-C", str(repo), *args], timeout=30)


def git_repo(repo, root):
    remote = git_value(repo, "remote", "get-url", "origin")
    dirty = git_value(repo, "status", "--porcelain", "--untracked-files=no")
    return {
        "path": safe_relative(repo, root),
        "commit": git_value(repo, "rev-parse", "HEAD"),
        "describe": git_value(repo, "describe", "--always", "--dirty", "--tags"),
        "origin": sanitized_text(remote) if remote else None,
        "tracked_worktree_dirty": bool(dirty),
        "tracked_change_count": len(dirty.splitlines()) if dirty else 0,
    }


def iter_files(root):
    if not root.is_dir():
        return
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_PARTS)
        base_path = pathlib.Path(base)
        for name in sorted(files):
            path = base_path / name
            if not path.is_file():
                continue
            yield path


def tree_receipt(root):
    digest = hashlib.sha256()
    count = 0
    total = 0
    for path in iter_files(root):
        relative = safe_relative(path, root)
        size = path.stat().st_size
        file_digest = sha256_file(path)
        digest.update(relative.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\n")
        count += 1
        total += size
    return {"sha256": digest.hexdigest(), "file_count": count, "bytes": total}


def file_receipt(path, root):
    value = {
        "path": safe_relative(path, root),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if path.is_symlink():
        value["symlink_target"] = os.readlink(path)
    return value


stack_root = next((path for path in STACK_CANDIDATES if path.is_dir()), None)
if stack_root is None:
    raise SystemExit("approved H3 stack root was not found")
comfy_root = stack_root / "ComfyUI"
if not comfy_root.is_dir():
    raise SystemExit("ComfyUI root was not found below the H3 stack")

os_release = {}
release_path = pathlib.Path("/etc/os-release")
if release_path.is_file():
    for line in release_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            os_release[key] = value.strip().strip('"')

gpu_query = command([
    "nvidia-smi",
    "--query-gpu=name,driver_version,memory.total,compute_cap",
    "--format=csv,noheader,nounits",
])

repos = [git_repo(comfy_root, stack_root)] if (comfy_root / ".git").is_dir() else []
custom_nodes_root = comfy_root / "custom_nodes"
custom_nodes = []
if custom_nodes_root.is_dir():
    for child in sorted(custom_nodes_root.iterdir(), key=lambda item: item.name.casefold()):
        if not child.is_dir() or child.name in EXCLUDED_PARTS:
            continue
        if (child / ".git").is_dir():
            repos.append(git_repo(child, stack_root))
        else:
            custom_nodes.append({"path": safe_relative(child, stack_root), **tree_receipt(child)})

models = []
models_root = comfy_root / "models"
for path in iter_files(models_root):
    item = {
        "path": safe_relative(path, models_root),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path) if HASH_MODELS else None,
    }
    if path.is_symlink():
        item["symlink_target"] = os.readlink(path)
    models.append(item)

critical_candidates = [
    stack_root / "incoming" / "launch-comfy.sh",
    stack_root / "incoming" / "install-stack.sh",
    stack_root / "incoming" / "h3-easy-33b6a795ea8f53354eb6b7854a731be49ef24a4e.tar.gz",
    stack_root / "incoming" / "nvidia_vfx-0.1.0.1-cp312-abi3-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",
    stack_root / "incoming" / "model-manifest.json",
    stack_root / "incoming" / "probe-stack.py",
    stack_root / "incoming" / "h3-keyframes-only" / "SOURCE.json",
    comfy_root / "extra_model_paths.yaml",
    comfy_root / "custom_nodes" / "h3-keyframes-only" / "SOURCE.json",
]
critical_files = [
    file_receipt(path, stack_root) for path in critical_candidates if path.is_file()
]

receipts_root = stack_root / "receipts"
receipt_files = [file_receipt(path, stack_root) for path in iter_files(receipts_root)]

env_python = stack_root / "env" / "bin" / "python"
python_version = command([str(env_python), "--version"]) if env_python.is_file() else None
freeze = command([str(env_python), "-m", "pip", "freeze"], timeout=180) if env_python.is_file() else None
packages = [sanitized_text(line) for line in freeze.splitlines()] if freeze else []

comfy_patch = git_value(comfy_root, "diff", "--binary", "--", "nodes.py", "comfy_extras/nodes_audio.py", "comfy_extras/nodes_video.py")
disk = shutil.disk_usage(stack_root)
mount = mount_summary(stack_root)

h3_source_commit = None
h3_source_path = comfy_root / "custom_nodes" / "h3-keyframes-only" / "SOURCE.json"
if h3_source_path.is_file():
    try:
        h3_source_commit = str(json.loads(h3_source_path.read_text(encoding="utf-8"))["commit"])
    except (OSError, KeyError, TypeError, ValueError):
        pass

payload = {
    "schema_version": "h3-stack-inventory-v1",
    "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "probe_mode": "read_only_full_model_hash" if HASH_MODELS else "read_only_fast",
    "system": {
        "os": {key: os_release.get(key) for key in ("ID", "VERSION_ID", "PRETTY_NAME")},
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "gpu_available": gpu_query is not None,
        "gpu_query": gpu_query,
        "mount": mount,
        "stack_disk_bytes": {"total": disk.total, "used": disk.used, "free": disk.free},
    },
    "layout": {
        "stack_root": str(stack_root),
        "comfy_root": str(comfy_root),
    },
    "python": {"version": python_version, "packages": sorted(packages)},
    "git_repositories": repos,
    "non_git_custom_nodes": custom_nodes,
    "h3_keyframes_source_commit": h3_source_commit,
    "models": models,
    "critical_files": critical_files,
    "receipt_files": receipt_files,
    "comfy_tracked_patch": comfy_patch or "",
    "tree_receipts": {
        "incoming": tree_receipt(stack_root / "incoming"),
        "benchmark": tree_receipt(stack_root / "benchmark"),
    },
}
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
'''


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _expected_model_manifest(root: Path) -> Mapping[str, Any]:
    path = root / "config/autodl-production-models.json"
    if not path.is_file():
        raise RuntimeError(f"missing local model manifest: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def compare_inventory(root: Path, inventory: Mapping[str, Any]) -> dict[str, Any]:
    expected_models = _expected_model_manifest(root)
    golden = json.loads(
        (root / "config/autodl-stack-fingerprint.json").read_text(encoding="utf-8")
    )
    live_models = {
        str(item.get("path")): item
        for item in inventory.get("models", [])
        if isinstance(item, Mapping)
    }
    missing_models: list[str] = []
    model_mismatches: list[dict[str, Any]] = []
    expected_paths: set[str] = set()
    for expected in expected_models.get("files", []):
        path = str(expected["repository_path"])
        expected_paths.add(path)
        live = live_models.get(path)
        if live is None:
            missing_models.append(path)
            continue
        differences = {}
        if int(live.get("bytes", -1)) != int(expected["bytes"]):
            differences["bytes"] = {"expected": expected["bytes"], "live": live.get("bytes")}
        if live.get("sha256") and live.get("sha256") != expected["sha256"]:
            differences["sha256"] = {"expected": expected["sha256"], "live": live.get("sha256")}
        if differences:
            model_mismatches.append({"path": path, "differences": differences})

    live_repos = {
        str(item.get("path")): item
        for item in inventory.get("git_repositories", [])
        if isinstance(item, Mapping)
    }
    expected_repo_commits = {
        "ComfyUI": golden["golden_runtime_evidence"]["comfy_commit"],
        "ComfyUI/custom_nodes/ComfyUI-KJNodes": golden["golden_runtime_evidence"]["kj_nodes_commit"],
        "ComfyUI/custom_nodes/Nvidia_RTX_Nodes_ComfyUI": golden["golden_runtime_evidence"]["rtx_nodes_commit"],
    }
    repo_mismatches = []
    for path, commit in expected_repo_commits.items():
        live = live_repos.get(path)
        if live is None or live.get("commit") != commit:
            repo_mismatches.append(
                {"path": path, "expected_commit": commit, "live_commit": live.get("commit") if live else None}
            )

    expected_h3_commit = golden["golden_runtime_evidence"]["h3_keyframes_source_commit"]
    live_h3_commit = inventory.get("h3_keyframes_source_commit")
    if live_h3_commit != expected_h3_commit:
        repo_mismatches.append(
            {"path": "ComfyUI/custom_nodes/h3-keyframes-only", "expected_commit": expected_h3_commit, "live_commit": live_h3_commit}
        )

    extra_model_files = sorted(
        path
        for path, item in live_models.items()
        if path not in expected_paths
        and int(item.get("bytes", 0)) > 1024 * 1024
        and Path(path).suffix.casefold() in {".bin", ".ckpt", ".gguf", ".pt", ".pth", ".safetensors"}
    )
    return {
        "schema_version": "h3-stack-comparison-v1",
        "inventory_sha256": _sha256_json(inventory),
        "model_hashes_checked": inventory.get("probe_mode") == "read_only_full_model_hash",
        "expected_model_bytes": expected_models.get("total_bytes"),
        "live_expected_model_bytes": sum(
            int(live_models[path].get("bytes", 0))
            for path in expected_paths
            if path in live_models
        ),
        "missing_models": sorted(missing_models),
        "model_mismatches": model_mismatches,
        "extra_model_files": extra_model_files,
        "repository_mismatches": repo_mismatches,
        "matches_known_golden_stack": not missing_models and not model_mismatches and not repo_mismatches,
        "gpu_validation_deferred": not bool(inventory.get("system", {}).get("gpu_available")),
    }


def _resolve(root: Path, value: str) -> Path:
    target = Path(value).expanduser()
    return target.resolve() if target.is_absolute() else (root / target).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--known-hosts", default="~/.config/broll-autodl/known_hosts")
    parser.add_argument("--hash-models", action="store_true", help="SHA-256 every production model file (reads about 156 GB on the current stack).")
    parser.add_argument("--from-inventory", help="Re-run only the local golden comparison for an existing inventory JSON.")
    args = parser.parse_args(argv)

    root = Path(args.project_root).expanduser().resolve()
    if args.from_inventory:
        inventory_path = _resolve(root, args.from_inventory)
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        comparison = compare_inventory(root, inventory)
        comparison_path = inventory_path.with_name("golden-comparison.json")
        comparison_path.write_text(
            json.dumps(comparison, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({
            "comparison": str(comparison_path),
            "matches_known_golden_stack": comparison["matches_known_golden_stack"],
            "missing_model_count": len(comparison["missing_models"]),
            "model_mismatch_count": len(comparison["model_mismatches"]),
            "repository_mismatch_count": len(comparison["repository_mismatches"]),
            "extra_model_file_count": len(comparison["extra_model_files"]),
            "gpu_validation_deferred": comparison["gpu_validation_deferred"],
        }, ensure_ascii=False, sort_keys=True))
        return 0

    credentials = AutoDLCredentials.load(root)
    if credentials.connection_mode != "ssh" or credentials.ssh_host is None or credentials.ssh_port is None:
        raise RuntimeError("the read-only audit requires current SSH-mode AutoDL credentials")
    endpoint = AutoDLSSHEndpoint(credentials.ssh_host, credentials.ssh_port, credentials.instance_uuid)
    client = AutoDLSSHClient(endpoint, credentials, known_hosts=_resolve(root, args.known_hosts))
    # AutoDL's no-card shell has no system Python at /usr/bin; its stable base
    # interpreter remains available at this path even while the GPU is detached.
    remote_args = ["/root/miniconda3/bin/python3", "-c", REMOTE_PROBE]
    if args.hash_models:
        remote_args.append("--hash-models")
    result = client.run(remote_args, timeout_seconds=3600 if args.hash_models else 300)
    inventory = json.loads(result.stdout)
    if not isinstance(inventory, Mapping):
        raise RuntimeError("remote inventory did not return a JSON object")

    stamp = str(inventory["collected_at"]).replace("-", "").replace(":", "")
    destination = root / "work/stack-audits" / stamp
    destination.mkdir(parents=True, exist_ok=False)
    inventory_path = destination / "stack-inventory.json"
    comparison_path = destination / "golden-comparison.json"
    inventory_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    comparison = compare_inventory(root, inventory)
    comparison_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({
        "inventory": str(inventory_path),
        "comparison": str(comparison_path),
        "matches_known_golden_stack": comparison["matches_known_golden_stack"],
        "missing_model_count": len(comparison["missing_models"]),
        "model_mismatch_count": len(comparison["model_mismatches"]),
        "repository_mismatch_count": len(comparison["repository_mismatches"]),
        "extra_model_file_count": len(comparison["extra_model_files"]),
        "gpu_validation_deferred": comparison["gpu_validation_deferred"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"outcome": "error", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
