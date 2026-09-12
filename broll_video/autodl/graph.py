"""Compile canonical H3 requests into the frozen AutoDL Comfy workflows."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from broll_video.h3.models import (
    H3InputError,
    H3Request,
    REFINE_2PASS_EXP_DENOISE,
    REFINE_2PASS_EXP_MODEL,
    REFINE_2PASS_EXP_SCALE,
    REFINE_2PASS_EXP_STEPS,
    REFINE_2PASS_INT8_EXP_DENOISE,
    REFINE_2PASS_INT8_EXP_MODEL,
    REFINE_2PASS_INT8_EXP_SCALE,
    REFINE_2PASS_INT8_EXP_STEPS,
    REFINE_2PASS_INT8_EXP_PASS1_STEPS,
    preflight_request,
)


WORKFLOW_VERSION = "autodl-h3-turbo-rtx4k-2026-08-24-v3"


@dataclass(frozen=True)
class ProfileSpec:
    name: str
    version: str
    template: str
    base_template: str
    cloud_compatibility: str = "verified_existing"
    model_manifest: str | None = None


# Do not mutate an established profile/template in place.  The metadata files
# for new profiles deliberately record the Comfy core-node requirement because
# the fixed instance's /object_info has not yet been audited.
PROFILE_SPECS = {
    "fast": ProfileSpec("fast", "fast-v1", "ref2v-fast.json", "ref2v-fast.json"),
    "precision_keyframes": ProfileSpec(
        "precision_keyframes", "precision-keyframes-v1", "keyframes-precision.json", "keyframes-precision.json"
    ),
    "ref_multimodal": ProfileSpec(
        "ref_multimodal", "ref-multimodal-v2", "ref2v-multimodal-v2.json", "ref2v-fast-rtx4k.json", "requires_object_info"
    ),
    "fl2v_explicit": ProfileSpec(
        "fl2v_explicit", "fl2v-explicit-v1", "fl2v-explicit-v1.json", "keyframes-precision.json", "requires_object_info"
    ),
    "precision_timed": ProfileSpec(
        "precision_timed", "precision-timed-v1", "precision-timed-v1.json", "keyframes-precision.json", "requires_object_info"
    ),
    "precision_timed_h3keyframes": ProfileSpec(
        "precision_timed_h3keyframes",
        "precision-timed-h3keyframes-v1",
        "precision-timed-h3keyframes-v1.json",
        "keyframes-precision.json",
        "requires_object_info",
    ),
    "refine_2pass_exp": ProfileSpec(
        "refine_2pass_exp",
        "refine-2pass-exp-v1",
        "refine-2pass-exp-v1.json",
        "refine-2pass-exp-v1.json",
        "requires_m5_deployment_audit",
        "refine-2pass-exp-v1.models.json",
    ),
    "refine_2pass_int8_exp": ProfileSpec(
        "refine_2pass_int8_exp",
        "refine-2pass-int8-exp-v1",
        "refine-2pass-int8-exp-v1.json",
        "refine-2pass-int8-exp-v1.json",
        "requires_m5_int8_deployment_audit",
        "refine-2pass-int8-exp-v1.models.json",
    ),
}
PROFILES = set(PROFILE_SPECS)
BASE_DIMENSIONS = {
    "21:9": (960, 416),
    "16:9": (864, 480),
    "4:3": (768, 576),
    "1:1": (640, 640),
    "3:4": (576, 768),
    "9:16": (480, 864),
}
FOUR_K_DIMENSIONS = {
    "21:9": (3840, 1648),
    "16:9": (3840, 2160),
    "4:3": (4096, 3072),
    "1:1": (3840, 3840),
    "3:4": (3072, 4096),
    "9:16": (2160, 3840),
}
REFINE_2PASS_DIMENSIONS = {
    ratio: (width * REFINE_2PASS_EXP_SCALE, height * REFINE_2PASS_EXP_SCALE)
    for ratio, (width, height) in BASE_DIMENSIONS.items()
}
REFINE_2PASS_INT8_DIMENSIONS = {
    ratio: (width * REFINE_2PASS_INT8_EXP_SCALE, height * REFINE_2PASS_INT8_EXP_SCALE)
    for ratio, (width, height) in BASE_DIMENSIONS.items()
}


@dataclass(frozen=True)
class UploadBinding:
    local_path: Path
    remote_name: str


@dataclass(frozen=True)
class CompiledWorkflow:
    prompt: dict[str, Any]
    fingerprint: str
    profile: str
    seed: int
    width: int
    height: int
    frame_count: int
    output_prefix: str
    uploads: tuple[UploadBinding, ...]
    profile_version: str
    deployment_gate: str | None = None
    reference_manifest: tuple[dict[str, Any], ...] = ()


def request_fingerprint(request: H3Request) -> str:
    """Hash the effective local-provider request, including input file bytes."""

    preflight_request(request, encode_local=False).require_ok()
    spec = _profile_spec(request)
    media = []
    for ordinal, asset in enumerate(request.media, start=1):
        source = Path(asset.source).expanduser().resolve()
        if not source.is_file():
            raise H3InputError(
                "AutoDL workflow requires local media files; remote/data media are unsupported"
            )
        media.append(
            {
                "role": asset.role,
                "manifest_ordinal": ordinal,
                "name": source.name,
                "size": source.stat().st_size,
                "sha256": _sha256_file(source),
                "source_origin": asset.source_origin,
                "rights_note": asset.rights_note,
                "semantic_role": asset.semantic_role,
                "must_preserve": list(asset.must_preserve),
                "may_change": list(asset.may_change),
                "used_by": list(asset.used_by),
                "prompt_label": asset.prompt_label,
                "anchor_time_ms": asset.anchor_time_ms,
                "frame_index": asset.frame_index,
            }
        )
    payload = {
        "provider": "autodl-comfy",
        "workflow_version": WORKFLOW_VERSION,
        "profile_version": spec.version,
        "workflow_template_sha256": _sha256_file(
            Path(__file__).with_name("workflows") / spec.template
        ),
        "base_workflow_template_sha256": _sha256_file(
            Path(__file__).with_name("workflows") / spec.base_template
        ),
        "model_manifest_sha256": (
            _sha256_file(Path(__file__).with_name("workflows") / spec.model_manifest)
            if spec.model_manifest
            else None
        ),
        "prompt": request.prompt,
        "duration": request.duration,
        "ratio": request.ratio,
        "resolution": request.resolution,
        "provider_profile": request.provider_profile,
        "seed": request.seed,
        "refine_pass2_model": request.refine_pass2_model,
        "refine_pass2_steps": request.refine_pass2_steps,
        "refine_pass2_denoise": request.refine_pass2_denoise,
        "refine_pass2_scale": request.refine_pass2_scale,
        "media": media,
    }
    if request.provider_profile == "refine_2pass_int8_exp":
        payload["experimental_canary"] = request.experimental_canary
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


class AutoDLGraphCompiler:
    def __init__(self, workflow_directory: Path | str | None = None) -> None:
        self.workflow_directory = Path(
            workflow_directory or Path(__file__).with_name("workflows")
        ).resolve()

    def compile(self, request: H3Request) -> CompiledWorkflow:
        self._provider_preflight(request)
        spec = _profile_spec(request)
        fingerprint = request_fingerprint(request)
        width, height = BASE_DIMENSIONS[request.ratio]
        frame_count = _frame_count(request.duration)
        seed = request.seed if request.seed is not None else int(fingerprint[:15], 16)
        uploads = tuple(
            UploadBinding(
                Path(asset.source).expanduser().resolve(),
                f"autodl/{fingerprint[:16]}/{index + 1:02d}-{Path(asset.source).name}",
            )
            for index, asset in enumerate(request.media)
        )
        if request.provider_profile == "precision_keyframes":
            prompt = self._compile_precision(
                request, uploads, width, height, frame_count, seed, fingerprint
            )
        elif request.provider_profile == "ref_multimodal":
            prompt = self._compile_ref_multimodal(
                request, uploads, width, height, frame_count, seed, fingerprint
            )
        elif request.provider_profile == "fl2v_explicit":
            prompt = self._compile_fl2v_explicit(
                request, uploads, width, height, frame_count, seed, fingerprint
            )
        elif request.provider_profile == "precision_timed":
            prompt = self._compile_precision_timed(
                request, uploads, width, height, frame_count, seed, fingerprint
            )
        elif request.provider_profile == "precision_timed_h3keyframes":
            prompt = self._compile_precision_timed_h3keyframes(
                request, uploads, width, height, frame_count, seed, fingerprint
            )
        elif request.provider_profile == "refine_2pass_exp":
            prompt = self._compile_refine_2pass_exp(
                request, uploads, width, height, frame_count, seed, fingerprint
            )
        elif request.provider_profile == "refine_2pass_int8_exp":
            prompt = self._compile_refine_2pass_int8_exp(
                request, uploads, width, height, frame_count, seed, fingerprint
            )
        else:
            prompt = self._compile_fast(
                request, uploads, width, height, frame_count, seed, fingerprint
            )
        return CompiledWorkflow(
            prompt=prompt,
            fingerprint=fingerprint,
            profile=request.provider_profile,
            seed=seed,
            width=width,
            height=height,
            frame_count=frame_count,
            output_prefix=f"video/autodl_{fingerprint[:16]}",
            uploads=uploads,
            profile_version=spec.version,
            deployment_gate=_deployment_gate(spec, request.provider_profile),
            reference_manifest=_compiled_reference_manifest(request),
        )

    def _provider_preflight(self, request: H3Request) -> None:
        preflight_request(request, encode_local=False).require_ok()
        _profile_spec(request)
        if request.ratio not in BASE_DIMENSIONS:
            raise H3InputError(
                "AutoDL generation requires one of 21:9, 16:9, 4:3, 1:1, 3:4, 9:16"
            )
        if request.provider_profile == "fast":
            if not request.media or any(asset.role != "reference_image" for asset in request.media):
                raise H3InputError("fast requires 1-9 local reference_image inputs")
            if len(request.media) > 9:
                raise H3InputError("fast accepts at most 9 reference images")
        elif request.provider_profile == "precision_keyframes":
            if any(asset.role != "reference_image" for asset in request.media):
                raise H3InputError("precision_keyframes accepts reference_image inputs only")
            if not 2 <= len(request.media) <= 6:
                raise H3InputError("precision_keyframes requires 2-6 storyboard images")
        elif request.provider_profile == "ref_multimodal":
            if not request.media or any(asset.role not in {"reference_image", "reference_video", "reference_audio"} for asset in request.media):
                raise H3InputError("ref_multimodal requires reference image/video/audio inputs")
        elif request.provider_profile == "fl2v_explicit":
            if len(request.media) > 2 or any(asset.role not in {"first_frame", "last_frame"} for asset in request.media):
                raise H3InputError("fl2v_explicit accepts only zero, one, or two first/last frame images")
        elif request.provider_profile == "precision_timed":
            if any(asset.role != "reference_image" for asset in request.media) or not 2 <= len(request.media) <= 6:
                raise H3InputError("precision_timed requires 2-6 reference_image keyframes")
            _validate_timed_anchors(request)
        elif request.provider_profile == "precision_timed_h3keyframes":
            if any(asset.role != "reference_image" for asset in request.media) or not 2 <= len(request.media) <= 6:
                raise H3InputError(
                    "precision_timed_h3keyframes requires 2-6 reference_image keyframes"
                )
            _validate_timed_anchors(request)
        elif request.provider_profile in {"refine_2pass_exp", "refine_2pass_int8_exp"}:
            roles = tuple(asset.role for asset in request.media)
            if roles not in {("first_frame",), ("last_frame",), ("first_frame", "last_frame")}:
                raise H3InputError(
                    f"{request.provider_profile} requires one first/last frame, or ordered first_frame then last_frame"
                )
            if request.resolution != "4K":
                raise H3InputError(f"{request.provider_profile} requires 4K final RTX output")
        for asset in request.media:
            source = Path(asset.source).expanduser().resolve()
            if not source.is_file():
                raise H3InputError(
                    "AutoDL production requires local reference files"
                )

    def _compile_fast(
        self,
        request: H3Request,
        uploads: tuple[UploadBinding, ...],
        width: int,
        height: int,
        frame_count: int,
        seed: int,
        fingerprint: str,
    ) -> dict[str, Any]:
        template_name = _template_name(request)
        prompt = self._load(template_name)
        self._remove_load_images(prompt)
        conditioning = prompt["136"]["inputs"]
        for key in list(conditioning):
            if key.startswith("ref_images.ref_image_"):
                del conditioning[key]
        for index, binding in enumerate(uploads):
            node_id = str(160 + index)
            prompt[node_id] = {
                "class_type": "LoadImage",
                "inputs": {"image": binding.remote_name},
            }
            conditioning[f"ref_images.ref_image_{index}"] = [node_id, 0]
        conditioning.update(
            {
                "prompt": _guard_audio(request.prompt, request.audio_policy),
                "width": width,
                "height": height,
                "length": frame_count,
                "ref_image_size": "match",
            }
        )
        if request.resolution == "4K":
            _configure_4k(prompt, request.ratio)
        prompt["129"]["inputs"]["noise_seed"] = seed
        prompt["92"]["inputs"]["filename_prefix"] = f"video/autodl_{fingerprint[:16]}"
        return prompt

    def _compile_precision(
        self,
        request: H3Request,
        uploads: tuple[UploadBinding, ...],
        width: int,
        height: int,
        frame_count: int,
        seed: int,
        fingerprint: str,
    ) -> dict[str, Any]:
        prompt = self._load("keyframes-precision.json")
        self._remove_load_images(prompt)
        conditioning = prompt["136"]["inputs"]
        for key in list(conditioning):
            if key.startswith("image_"):
                del conditioning[key]
        explicit_positions = [
            asset.frame_index is not None or asset.anchor_time_ms is not None
            for asset in request.media
        ]
        if any(explicit_positions):
            if not all(explicit_positions):
                raise H3InputError(
                    "precision_keyframes cannot mix timed and untimed storyboard anchors"
                )
            resolved = tuple(
                _resolved_anchor_frame(asset, request.duration, frame_count)
                for asset in request.media
            )
            if (
                tuple(sorted(resolved)) != resolved
                or len(set(resolved)) != len(resolved)
                or resolved[0] != 0
                or resolved[-1] >= frame_count
            ):
                raise H3InputError(
                    "precision_keyframes semantic anchors must be unique, ordered, start at frame 0, and stay inside the H3 grid"
                )
            positions = tuple(str(value) for value in resolved)
        else:
            positions = _positions(len(uploads))
        alignment = "; ".join(
            f"Picture {index + 1} aligns with {position} of the target video"
            for index, position in enumerate(positions)
        )
        for index, binding in enumerate(uploads):
            node_id = str(160 + index)
            prompt[node_id] = {
                "class_type": "LoadImage",
                "inputs": {"image": binding.remote_name},
            }
            conditioning[f"image_{index + 1}"] = [node_id, 0]
        conditioning.update(
            {
                "prompt": f"KEYFRAME ALIGNMENT: {alignment}.\n\n{_guard_audio(request.prompt, request.audio_policy)}",
                "width": width,
                "height": height,
                "length": frame_count,
                "positions": ", ".join(positions),
            }
        )
        if request.resolution == "4K":
            target_width, target_height = FOUR_K_DIMENSIONS[request.ratio]
            prompt["149"] = {
                "class_type": "RTXVideoSuperResolution",
                "inputs": {
                    "images": ["122", 0],
                    "resize_type": "target dimensions",
                    "resize_type.width": target_width,
                    "resize_type.height": target_height,
                    "quality": "ULTRA",
                },
            }
            prompt["130"]["inputs"]["images"] = ["149", 0]
        prompt["129"]["inputs"]["noise_seed"] = seed
        prompt["92"]["inputs"]["filename_prefix"] = f"video/autodl_{fingerprint[:16]}"
        return prompt

    def _compile_ref_multimodal(
        self,
        request: H3Request,
        uploads: tuple[UploadBinding, ...],
        width: int,
        height: int,
        frame_count: int,
        seed: int,
        fingerprint: str,
    ) -> dict[str, Any]:
        """Wire only documented Comfy core nodes; execution remains environment-gated."""
        prompt = self._load(_template_name(request))
        self._remove_load_images(prompt)
        conditioning = prompt["136"]["inputs"]
        for key in list(conditioning):
            if key.startswith(("ref_images.", "ref_videos.", "ref_video_audios.", "ref_audios.")):
                del conditioning[key]
        counters = {"image": 0, "video": 0, "audio": 0}
        for index, (asset, binding) in enumerate(zip(request.media, uploads), start=160):
            if asset.kind == "image":
                prompt[str(index)] = {"class_type": "LoadImage", "inputs": {"image": binding.remote_name}}
                conditioning[f"ref_images.ref_image_{counters['image']}"] = [str(index), 0]
                counters["image"] += 1
            elif asset.kind == "video":
                # Core LoadVideo -> GetVideoComponents supplies both IMAGE frames
                # and the same indexed soundtrack expected by Ref2VA.
                prompt[str(index)] = {"class_type": "LoadVideo", "inputs": {"file": binding.remote_name}}
                component_id = str(index + 100)
                prompt[component_id] = {"class_type": "GetVideoComponents", "inputs": {"video": [str(index), 0]}}
                ordinal = counters["video"]
                conditioning[f"ref_videos.ref_video_{ordinal}"] = [component_id, 0]
                conditioning[f"ref_video_audios.ref_video_audio_{ordinal}"] = [component_id, 1]
                counters["video"] += 1
            else:
                prompt[str(index)] = {"class_type": "LoadAudio", "inputs": {"audio": binding.remote_name}}
                conditioning[f"ref_audios.ref_audio_{counters['audio']}"] = [str(index), 0]
                counters["audio"] += 1
        conditioning.update(
            {
                "prompt": _reference_prompt(request),
                "width": width,
                "height": height,
                "length": frame_count,
                "ref_image_size": "match",
            }
        )
        if request.resolution == "4K":
            _configure_4k(prompt, request.ratio)
        prompt["129"]["inputs"]["noise_seed"] = seed
        prompt["92"]["inputs"]["filename_prefix"] = f"video/autodl_{fingerprint[:16]}"
        return prompt

    def _compile_fl2v_explicit(
        self,
        request: H3Request,
        uploads: tuple[UploadBinding, ...],
        width: int,
        height: int,
        frame_count: int,
        seed: int,
        fingerprint: str,
    ) -> dict[str, Any]:
        prompt = self._load("keyframes-precision.json")
        self._remove_load_images(prompt)
        prompt["136"]["class_type"] = "MiniMaxH3ImageToVideo"
        inputs = prompt["136"]["inputs"]
        for key in list(inputs):
            if key.startswith("image_") or key == "positions":
                del inputs[key]
        for index, (asset, binding) in enumerate(zip(request.media, uploads), start=160):
            prompt[str(index)] = {"class_type": "LoadImage", "inputs": {"image": binding.remote_name}}
            inputs[asset.role] = [str(index), 0]
        inputs.update({"prompt": _guard_audio(request.prompt, request.audio_policy), "width": width, "height": height, "length": frame_count})
        if request.resolution == "4K":
            _add_4k_to_fl2v(prompt, request.ratio)
        prompt["129"]["inputs"]["noise_seed"] = seed
        prompt["92"]["inputs"]["filename_prefix"] = f"video/autodl_{fingerprint[:16]}"
        return prompt

    def _compile_precision_timed(
        self,
        request: H3Request,
        uploads: tuple[UploadBinding, ...],
        width: int,
        height: int,
        frame_count: int,
        seed: int,
        fingerprint: str,
    ) -> dict[str, Any]:
        # Start from the explicit FL2VA conditioning node, then chain the
        # official AddGuide core node in manifest order.  We do not normalize
        # or redistribute anchors: each resolved source value is preserved.
        prompt = self._compile_fl2v_explicit(
            H3Request(
                prompt=request.prompt,
                duration=request.duration,
                ratio=request.ratio,
                resolution=request.resolution,
                provider_profile="fl2v_explicit",
                seed=request.seed,
            ),
            (), width, height, frame_count, seed, fingerprint,
        )
        previous = "136"
        for index, (asset, binding) in enumerate(zip(request.media, uploads), start=160):
            image_id = str(index)
            guide_id = str(index + 100)
            prompt[image_id] = {"class_type": "LoadImage", "inputs": {"image": binding.remote_name}}
            prompt[guide_id] = {
                "class_type": "MiniMaxH3AddGuide",
                "inputs": {
                    "positive": [previous, 0],
                    "vae": ["119", 0],
                    "latent": ["136", 1],
                    "image": [image_id, 0],
                    "frame_idx": _resolved_anchor_frame(asset, request.duration, frame_count),
                },
            }
            previous = guide_id
        prompt["126"]["inputs"]["conditioning"] = [previous, 0]
        return prompt

    def _compile_precision_timed_h3keyframes(
        self,
        request: H3Request,
        uploads: tuple[UploadBinding, ...],
        width: int,
        height: int,
        frame_count: int,
        seed: int,
        fingerprint: str,
    ) -> dict[str, Any]:
        """Compile immutable timed anchors through the live-proven H3Keyframes node."""

        prompt = self._load("keyframes-precision.json")
        self._remove_load_images(prompt)
        conditioning = prompt["136"]["inputs"]
        for key in list(conditioning):
            if key.startswith("image_"):
                del conditioning[key]
        positions = tuple(
            str(_resolved_anchor_frame(asset, request.duration, frame_count))
            for asset in request.media
        )
        alignment = "; ".join(
            f"Picture {index + 1} is anchored at absolute frame {position}"
            for index, position in enumerate(positions)
        )
        for index, binding in enumerate(uploads):
            node_id = str(160 + index)
            prompt[node_id] = {
                "class_type": "LoadImage",
                "inputs": {"image": binding.remote_name},
            }
            conditioning[f"image_{index + 1}"] = [node_id, 0]
        conditioning.update(
            {
                "prompt": f"KEYFRAME ALIGNMENT: {alignment}.\n\n{_guard_audio(request.prompt, request.audio_policy)}",
                "width": width,
                "height": height,
                "length": frame_count,
                "positions": ", ".join(positions),
            }
        )
        if request.resolution == "4K":
            target_width, target_height = FOUR_K_DIMENSIONS[request.ratio]
            prompt["149"] = {
                "class_type": "RTXVideoSuperResolution",
                "inputs": {
                    "images": ["122", 0],
                    "resize_type": "target dimensions",
                    "resize_type.width": target_width,
                    "resize_type.height": target_height,
                    "quality": "ULTRA",
                },
            }
            prompt["130"]["inputs"]["images"] = ["149", 0]
        prompt["129"]["inputs"]["noise_seed"] = seed
        prompt["92"]["inputs"]["filename_prefix"] = f"video/autodl_{fingerprint[:16]}"
        return prompt

    def _compile_refine_2pass_exp(
        self,
        request: H3Request,
        uploads: tuple[UploadBinding, ...],
        width: int,
        height: int,
        frame_count: int,
        seed: int,
        fingerprint: str,
    ) -> dict[str, Any]:
        """Compile the isolated H3 Easy two-pass experiment.

        The graph deliberately follows the upstream pass-2 topology: retain
        pass one's AV latent, transform only its video latent, rebuild only the
        resolution-bound FL2VA conditioning, and decode pass-one audio for the
        final mux.  Its deployment gate is intentionally stronger than normal
        new-profile object-info checks because the fixed instance has not been
        approved for H3 Easy or the experimental W4A8 model.
        """

        prompt = self._load("refine-2pass-exp-v1.json")
        self._remove_load_images(prompt)
        easy_inputs = prompt["136"]["inputs"]
        for key in list(easy_inputs):
            if key.startswith(("media_", "media_type_")):
                del easy_inputs[key]
        for index, binding in enumerate(uploads, start=1):
            node_id = str(160 + index - 1)
            prompt[node_id] = {
                "class_type": "LoadImage",
                "inputs": {"image": binding.remote_name},
            }
            easy_inputs[f"media_{index}"] = [node_id, 0]
            easy_inputs[f"media_type_{index}"] = "image"

        # MiniMaxH3Easy rounds its seconds input to H3's 17k+5 lattice.  Feed
        # the already canonical frame duration so it exactly agrees with the
        # provider-wide ceiling rule for every accepted 4–15 second request.
        easy_inputs.update(
            {
                "mode": "image",
                "prompt": _guard_audio(request.prompt, request.audio_policy),
                "resolution": "custom",
                "aspect_ratio": request.ratio,
                "width": width,
                "height": height,
                "seconds": frame_count / 24.0,
                "fps": 24.0,
                "keyframe_role": "last" if request.media[0].role == "last_frame" else "first",
                "ref_image_size": "match",
                "reference_mention_mode": "index",
                "prompt_optimizer_settings": False,
                "prompt_optimizer_scene_guide": "none",
            }
        )
        pass2_width, pass2_height = REFINE_2PASS_DIMENSIONS[request.ratio]
        prompt["211"]["inputs"].update({"width": pass2_width, "height": pass2_height})
        prompt["215"]["inputs"]["unet_name"] = request.refine_pass2_model
        prompt["219"]["inputs"].update(
            {
                "steps": request.refine_pass2_steps,
                "denoise": request.refine_pass2_denoise,
            }
        )
        prompt["129"]["inputs"]["noise_seed"] = seed
        prompt["220"]["inputs"]["noise_seed"] = (seed + 1) % (2**63)
        _configure_4k(prompt, request.ratio)
        prompt["92"]["inputs"]["filename_prefix"] = f"video/autodl_{fingerprint[:16]}"
        return prompt

    def _compile_refine_2pass_int8_exp(
        self,
        request: H3Request,
        uploads: tuple[UploadBinding, ...],
        width: int,
        height: int,
        frame_count: int,
        seed: int,
        fingerprint: str,
    ) -> dict[str, Any]:
        """Compile the no-new-model INT8 H3 Easy two-pass experiment.

        Both samplers deliberately share the same fixed-instance FL2VA INT8
        branch.  The second pass only rebuilds its video latent and H3 Easy
        conditioning, then concatenates the pass-one audio latent unchanged.
        Runtime deployment remains fail-closed until the instance attestation
        and measured canary have been recorded.
        """

        prompt = self._load("refine-2pass-int8-exp-v1.json")
        self._remove_load_images(prompt)
        easy_inputs = prompt["136"]["inputs"]
        for key in list(easy_inputs):
            if key.startswith(("media_", "media_type_")):
                del easy_inputs[key]
        for index, binding in enumerate(uploads, start=1):
            node_id = str(160 + index - 1)
            prompt[node_id] = {
                "class_type": "LoadImage",
                "inputs": {"image": binding.remote_name},
            }
            easy_inputs[f"media_{index}"] = [node_id, 0]
            easy_inputs[f"media_type_{index}"] = "image"
        easy_inputs.update(
            {
                "mode": "image",
                "prompt": _guard_audio(request.prompt, request.audio_policy),
                "resolution": "custom",
                "aspect_ratio": request.ratio,
                "width": width,
                "height": height,
                "seconds": frame_count / 24.0,
                "fps": 24.0,
                "keyframe_role": "last" if request.media[0].role == "last_frame" else "first",
                "ref_image_size": "match",
                "reference_mention_mode": "index",
                "prompt_optimizer_settings": False,
                "prompt_optimizer_scene_guide": "none",
            }
        )
        pass2_width, pass2_height = REFINE_2PASS_INT8_DIMENSIONS[request.ratio]
        prompt["211"]["inputs"].update({"width": pass2_width, "height": pass2_height})
        # The immutable pass-2 model control documents that pass two uses the
        # same attested INT8 artifact; its graph link intentionally shares the
        # pass-one model object rather than loading another model.
        if request.refine_pass2_model != REFINE_2PASS_INT8_EXP_MODEL:
            raise H3InputError("refine_2pass_int8_exp pass-2 model is not the attested FL2VA INT8 artifact")
        prompt["124"]["inputs"]["steps"] = REFINE_2PASS_INT8_EXP_PASS1_STEPS
        prompt["219"]["inputs"].update(
            {"steps": REFINE_2PASS_INT8_EXP_STEPS, "denoise": REFINE_2PASS_INT8_EXP_DENOISE}
        )
        prompt["129"]["inputs"]["noise_seed"] = seed
        prompt["220"]["inputs"]["noise_seed"] = (seed + 1) % (2**63)
        _configure_4k(prompt, request.ratio)
        prompt["92"]["inputs"]["filename_prefix"] = f"video/autodl_{fingerprint[:16]}"
        return prompt

    def _load(self, name: str) -> dict[str, Any]:
        path = self.workflow_directory / name
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise H3InputError(f"cannot load AutoDL workflow template: {name}") from exc
        prompt = payload.get("prompt", payload)
        if not isinstance(prompt, dict):
            raise H3InputError(f"invalid AutoDL workflow template: {name}")
        return deepcopy(prompt)

    @staticmethod
    def _remove_load_images(prompt: dict[str, Any]) -> None:
        for node_id in [
            node_id
            for node_id, node in prompt.items()
            if isinstance(node, dict) and node.get("class_type") == "LoadImage"
        ]:
            del prompt[node_id]


def _frame_count(duration_seconds: int) -> int:
    """Round up to H3's 17k+5 frame grid so output is never shorter than requested."""

    return int(math.ceil((duration_seconds * 24 - 5) / 17) * 17 + 5)


def _profile_spec(request: H3Request) -> ProfileSpec:
    try:
        return PROFILE_SPECS[request.provider_profile]
    except KeyError as exc:
        raise H3InputError(f"unsupported AutoDL profile: {request.provider_profile}") from exc


def _deployment_gate(spec: ProfileSpec, profile: str) -> str | None:
    if spec.cloud_compatibility == "verified_existing":
        return None
    if spec.cloud_compatibility == "requires_m5_deployment_audit":
        return f"requires_m5_deployment_audit: {profile}"
    if spec.cloud_compatibility == "requires_m5_int8_deployment_audit":
        return f"requires_m5_int8_deployment_audit: {profile}"
    return f"requires_instance_object_info: {profile}"


def _compiled_reference_manifest(request: H3Request) -> tuple[dict[str, Any], ...]:
    ordinals = {"image": 0, "video": 0, "audio": 0}
    manifest: list[dict[str, Any]] = []
    for manifest_ordinal, asset in enumerate(request.media, start=1):
        ordinals[asset.kind] += 1
        h3_label = {"image": "Picture", "video": "Video", "audio": "Audio"}[asset.kind]
        source = Path(asset.source).expanduser().resolve()
        manifest.append(
            {
                "manifest_ordinal": manifest_ordinal,
                "h3_ordinal": ordinals[asset.kind],
                "h3_type": asset.kind,
                "h3_label": f"<{h3_label} {ordinals[asset.kind]}>",
                "source": str(source),
                "sha256": _sha256_file(source),
                "role": asset.role,
                "source_origin": asset.source_origin,
                "rights_note": asset.rights_note,
                "semantic_role": asset.semantic_role,
                "prompt_label": asset.prompt_label,
                "must_preserve": list(asset.must_preserve),
                "may_change": list(asset.may_change),
                "used_by": list(asset.used_by),
                "anchor_time_ms": asset.anchor_time_ms,
                "frame_index": asset.frame_index,
            }
        )
    return tuple(manifest)


def _reference_prompt(request: H3Request) -> str:
    lines = ["REFERENCE CONTRACT — use the typed H3 labels exactly:"]
    for entry in _compiled_reference_manifest(request):
        role = entry["semantic_role"] or entry["role"]
        label = entry["h3_label"]
        display = f" ({entry['prompt_label']})" if entry["prompt_label"] else ""
        preserve = "; ".join(entry["must_preserve"]) or "no explicit preservation constraints"
        change = "; ".join(entry["may_change"]) or "no explicit permitted changes"
        lines.append(
            f"{label}{display}: role={role}; must preserve: {preserve}; may change: {change}."
        )
    return "\n".join(lines) + "\n\n" + _guard_audio(
        request.prompt, request.audio_policy
    )


def _validate_timed_anchors(request: H3Request) -> None:
    frame_count = _frame_count(request.duration)
    seen: set[int] = set()
    for asset in request.media:
        if (asset.anchor_time_ms is None) == (asset.frame_index is None):
            raise H3InputError(
                "each precision_timed keyframe requires exactly one of anchor_time_ms or frame_index"
            )
        if asset.anchor_time_ms is not None:
            if asset.anchor_time_ms > request.duration * 1000:
                raise H3InputError("anchor_time_ms is outside the requested duration")
            # Do not silently round a semantic beat onto another video frame.
            if asset.anchor_time_ms * 24 % 1000:
                raise H3InputError("anchor_time_ms must align to the 24 FPS grid (125 ms increments)")
        frame = _resolved_anchor_frame(asset, request.duration, frame_count)
        if not 0 <= frame < frame_count:
            raise H3InputError("keyframe anchor is outside the H3 5+17n frame grid")
        if frame in seen:
            raise H3InputError("precision_timed keyframe anchors conflict on the same frame")
        seen.add(frame)


def _resolved_anchor_frame(asset: Any, duration: int, frame_count: int) -> int:
    if asset.frame_index is not None:
        return asset.frame_index
    if asset.anchor_time_ms is None:
        raise H3InputError("timed keyframe is missing its anchor")
    return asset.anchor_time_ms * 24 // 1000


def _template_name(request: H3Request) -> str:
    if request.provider_profile == "precision_keyframes":
        return "keyframes-precision.json"
    return "ref2v-fast-rtx4k.json" if request.resolution == "4K" else "ref2v-fast.json"


def _add_4k_to_fl2v(prompt: dict[str, Any], ratio: str) -> None:
    target_width, target_height = FOUR_K_DIMENSIONS[ratio]
    prompt["149"] = {
        "class_type": "RTXVideoSuperResolution",
        "inputs": {
            "images": ["122", 0],
            "resize_type": "target dimensions",
            "resize_type.width": target_width,
            "resize_type.height": target_height,
            "quality": "ULTRA",
        },
    }
    prompt["130"]["inputs"]["images"] = ["149", 0]


def _configure_4k(prompt: dict[str, Any], ratio: str) -> None:
    target_width, target_height = FOUR_K_DIMENSIONS[ratio]
    node = prompt.get("149")
    if not isinstance(node, dict) or node.get("class_type") != "RTXVideoSuperResolution":
        raise H3InputError("4K workflow is missing RTXVideoSuperResolution")
    node["inputs"].update(
        {
            "resize_type": "target dimensions",
            "resize_type.width": target_width,
            "resize_type.height": target_height,
            "quality": "ULTRA",
        }
    )
    node["inputs"].pop("resize_type.scale", None)


def _positions(count: int) -> tuple[str, ...]:
    if count == 1:
        return ("0%",)
    return tuple(f"{round(index * 100 / (count - 1), 3):g}%" for index in range(count))


def _guard_audio(prompt: str, audio_policy: str) -> str:
    if audio_policy == "silent":
        guard = (
            "AUDIO POLICY: COMPLETE SILENCE for the entire video. Generate no audio track "
            "content: no music, soundtrack, rhythm, dialogue, narration, speech, voice, "
            "vocalization, environmental sound, ambience, Foley, action sound, UI sound, "
            "or transition sound."
        )
    elif audio_policy == "sfx_only":
        guard = (
            "AUDIO POLICY: only synchronized diegetic environmental and visible physical "
            "action sounds. No background music, soundtrack, melody, singing, humming, "
            "dialogue, narration, speech, voice, vocalization, UI voice, or off-screen sound."
        )
    else:
        guard = (
            "AUDIO POLICY: synchronized dialogue only when explicitly scripted, plus diegetic "
            "environmental and action sound effects. No background music, soundtrack, melody, "
            "singing, humming, or unscripted voices."
        )
    return prompt.rstrip() + "\n\n" + guard


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
