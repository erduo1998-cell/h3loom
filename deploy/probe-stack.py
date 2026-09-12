#!/usr/bin/env python3
"""Fail-closed live contract probe for the fixed AutoDL H3 stack."""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time
import urllib.request
from typing import Any


BASE = "http://127.0.0.1:8188"
STACK_ROOT = pathlib.Path("/root/autodl-tmp/h3-stack")
# Every class used by the frozen 7x15s A/B and 6s M5 benchmark.  Loading
# ComfyUI successfully is insufficient: a missing custom node otherwise only
# surfaces after an expensive prompt submission.
REQUIRED_INPUTS: dict[str, set[str]] = {
    "UNETLoader": {"unet_name", "weight_dtype"},
    "CLIPLoader": {"clip_name", "type"},
    "VAELoader": {"vae_name"},
    "LoraLoaderModelOnly": {"model", "lora_name", "strength_model"},
    "MiniMaxH3SigmaShift": {"model", "shift_video", "shift_audio"},
    "MiniMaxH3ReferenceToVideo": {"clip", "vae", "audio_vae", "prompt", "width", "height", "length", "ref_image_size"},
    "MiniMaxH3ImageToVideo": {"clip", "vae", "prompt", "width", "height", "length"},
    "H3Keyframes": {"clip", "vae", "prompt", "width", "height", "length", "positions"},
    "BasicGuider": {"model", "conditioning"},
    "BasicScheduler": {"model", "scheduler", "steps", "denoise"},
    "KSamplerSelect": {"sampler_name"},
    "RandomNoise": {"noise_seed"},
    "SamplerCustomAdvanced": {"noise", "guider", "sampler", "sigmas", "latent_image"},
    "VAEDecode": {"samples", "vae"},
    "VAEDecodeAudio": {"samples", "vae"},
    "LoadImage": {"image"},
    "LoadVideo": {"file"},
    "GetVideoComponents": {"video"},
    "ImageScale": {"image", "upscale_method", "width", "height", "crop"},
    "PathchSageAttentionKJ": {"model", "sage_attention"},
    "RTXVideoSuperResolution": {"images", "resize_type", "quality"},
    "CreateVideo": {"images", "fps"},
    "SaveVideo": {"video", "filename_prefix", "format", "codec"},
    "LTXVSeparateAVLatent": {"av_latent"},
    "LTXVConcatAVLatent": {"video_latent", "audio_latent"},
    "MiniMaxH3EasyModelAdapter": {"text_encoder", "video_vae", "audio_vae"},
    "MiniMaxH3Easy": {"h3_bundle", "mode", "prompt", "resolution", "aspect_ratio", "width", "height", "seconds", "advanced", "fps", "keyframe_role", "ref_image_size", "reference_mention_mode", "prompt_optimizer_settings", "prompt_optimizer_scene_guide"},
    "MiniMaxH3EasyOutput": {"h3_context"},
    "MiniMaxH3EasySecondPassConditioning": {"h3_context", "second_pass_video_latent"},
}


def get_json(path: str) -> Any:
    with urllib.request.urlopen(BASE + path, timeout=60) as response:
        return json.load(response)


def node_schema_inputs(schema: dict[str, Any]) -> set[str]:
    inputs = schema.get("input", {}) if isinstance(schema, dict) else {}
    names: set[str] = set()
    for group in ("required", "optional", "hidden"):
        values = inputs.get(group, {}) if isinstance(inputs, dict) else {}
        if isinstance(values, dict):
            names.update(str(name) for name in values)
    return names


def schema_accepts_input_name(schema: dict[str, Any], name: str) -> bool:
    """Recognize Comfy's documented DynamicCombo/AutoGrow child sockets.

    These children are flattened in an API prompt (for example
    ``resize_type.width``), while ``/object_info`` exposes their schema below
    the parent input.  Ordinary unknown inputs remain failures.
    """
    if name in node_schema_inputs(schema):
        return True
    inputs = schema.get("input", {}) if isinstance(schema, dict) else {}
    for group in ("required", "optional", "hidden"):
        values = inputs.get(group, {}) if isinstance(inputs, dict) else {}
        if not isinstance(values, dict):
            continue
        for parent, descriptor in values.items():
            if not isinstance(descriptor, list) or len(descriptor) < 2 or not isinstance(descriptor[1], dict):
                continue
            kind, options = descriptor[0], descriptor[1]
            if kind == "COMFY_DYNAMICCOMBO_V3" and name.startswith(f"{parent}."):
                child = name.split(".", 1)[1]
                for option in options.get("options", []):
                    nested = option.get("inputs", {}) if isinstance(option, dict) else {}
                    for nested_group in ("required", "optional"):
                        if child in (nested.get(nested_group, {}) if isinstance(nested, dict) else {}):
                            return True
            if kind == "COMFY_AUTOGROW_V3" and name.startswith(f"{parent}."):
                child = name.split(".", 1)[1]
                template = options.get("template", {})
                prefix = template.get("prefix", "") if isinstance(template, dict) else ""
                if isinstance(prefix, str) and child.startswith(prefix):
                    return True
    return False


def prompt_requirements(prompt_root: pathlib.Path) -> dict[str, set[str]]:
    requirements: dict[str, set[str]] = {}
    prompt_paths = sorted(prompt_root.rglob("prompt.json"))
    if not prompt_paths:
        raise ValueError(f"no prompt.json files below {prompt_root}")
    for path in prompt_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"invalid prompt object: {path}")
        for node in payload.values():
            if not isinstance(node, dict):
                continue
            class_type = node.get("class_type")
            inputs = node.get("inputs", {})
            if not isinstance(class_type, str) or not isinstance(inputs, dict):
                continue
            requirements.setdefault(class_type, set()).update(str(name) for name in inputs)
    return requirements


def smoke_rtx_4k(width: int, height: int) -> dict[str, object]:
    if width <= 0 or height <= 0 or width * height > 16 * 1024 * 1024:
        raise ValueError("RTX smoke target must be positive and at most 16 megapixels")
    script = f"""
import json
import torch
import nvvfx
source = torch.zeros((3, {height // 4}, {width // 4}), device='cuda', dtype=torch.float32)
with nvvfx.VideoSuperRes(nvvfx.effects.QualityLevel.ULTRA) as effect:
    effect.output_width = {width}
    effect.output_height = {height}
    effect.load()
    result = torch.from_dlpack(effect.run(source).image).clone()
torch.cuda.synchronize()
if tuple(result.shape) != (3, {height}, {width}):
    raise SystemExit(f'unexpected RTX output shape: {{tuple(result.shape)}}')
print(json.dumps({{'output_shape': list(result.shape), 'max_memory_allocated': torch.cuda.max_memory_allocated(), 'gpu_name': torch.cuda.get_device_name(0)}}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script], check=True, text=True, capture_output=True, timeout=180
    )
    return json.loads(completed.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt-root", type=pathlib.Path, help="Frozen compiled prompts to validate exactly.")
    parser.add_argument("--smoke-rtx-4k", action="store_true", help="Run one local 4K VFX frame before paid prompts.")
    parser.add_argument("--rtx-width", type=int, default=3840)
    parser.add_argument("--rtx-height", type=int, default=2880)
    args = parser.parse_args()

    system_stats = get_json("/system_stats")
    object_info = get_json("/object_info")
    nodes = object_info.get("nodes", object_info)
    if not isinstance(nodes, dict):
        raise SystemExit("object_info did not contain a node mapping")

    expected = {name: set(inputs) for name, inputs in REQUIRED_INPUTS.items()}
    if args.prompt_root:
        try:
            for class_type, inputs in prompt_requirements(args.prompt_root).items():
                expected.setdefault(class_type, set()).update(inputs)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise SystemExit(f"compiled prompt contract failed: {exc}") from exc

    missing_nodes = sorted(set(expected) - set(nodes))
    missing_inputs: dict[str, list[str]] = {}
    for name, needed in expected.items():
        if name not in nodes:
            continue
        absent = sorted(input_name for input_name in needed if not schema_accepts_input_name(nodes[name], input_name))
        if absent:
            missing_inputs[name] = absent

    rtx_smoke: dict[str, object] | None = None
    if not missing_nodes and not missing_inputs and args.smoke_rtx_4k:
        rtx_smoke = smoke_rtx_4k(args.rtx_width, args.rtx_height)

    receipt = {
        "schema_version": "2.0",
        "recorded_at": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
        "required_nodes": sorted(expected),
        "missing_nodes": missing_nodes,
        "missing_inputs": missing_inputs,
        "prompt_root": str(args.prompt_root) if args.prompt_root else None,
        "rtx_smoke": rtx_smoke,
        "system_stats": system_stats,
    }
    receipt_root = STACK_ROOT / "receipts"
    receipt_root.mkdir(parents=True, exist_ok=True)
    path = receipt_root / f"stack-probe-{receipt['recorded_at']}.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(path), "missing_nodes": missing_nodes, "missing_inputs": missing_inputs, "rtx_smoke": rtx_smoke}, ensure_ascii=False))
    return 1 if missing_nodes or missing_inputs else 0


if __name__ == "__main__":
    raise SystemExit(main())
