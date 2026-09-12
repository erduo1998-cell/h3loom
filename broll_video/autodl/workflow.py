"""AutoDL-only H3 compiler namespace built on the frozen legacy graph templates."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from broll_video.h3.models import H3InputError, H3Request
from broll_video.h3.prompt_gate import extract_final_h3_conditioning
from .graph import (
    CompiledWorkflow,
    UploadBinding,
    AutoDLGraphCompiler,
    request_fingerprint as legacy_request_fingerprint,
)


WORKFLOW_VERSION = "autodl-h3-turbo-rtx4k-2026-08-29-v4"
FINGERPRINT_SCHEME = "autodl-compiled-workflow-v1"
_LEGACY_AUDIO_GUARD = re.compile(r"\n\nAUDIO POLICY:.*\Z", flags=re.DOTALL)


class AutoDLWorkflowCompiler:
    """Expose only the two approved AutoDL profiles."""

    def __init__(self) -> None:
        self._legacy_graph_compiler = AutoDLGraphCompiler()

    def compile(self, request: H3Request) -> CompiledWorkflow:
        if request.provider_profile not in {"fast", "precision_keyframes"}:
            raise H3InputError(
                "AutoDL production supports only fast or precision_keyframes"
            )
        legacy = self._legacy_graph_compiler.compile(request)
        fingerprint = _canonical_sha256(
            {
                "provider": "autodl-comfy",
                "workflow_version": WORKFLOW_VERSION,
                "frozen_graph_request_fingerprint": legacy_request_fingerprint(request),
                "audio_policy": request.audio_policy,
                "production_contract": request.production_contract,
            }
        )
        uploads = tuple(
            UploadBinding(
                item.local_path,
                f"autodl/{fingerprint[:16]}/{index:02d}-{item.local_path.name}",
            )
            for index, item in enumerate(legacy.uploads, start=1)
        )
        replacements = {
            old.remote_name: new.remote_name
            for old, new in zip(legacy.uploads, uploads)
        }
        prompt = _replace_values(deepcopy(legacy.prompt), replacements)
        conditioning_prompt = str(prompt["136"]["inputs"]["prompt"])
        conditioning_prompt = _LEGACY_AUDIO_GUARD.sub("", conditioning_prompt).rstrip()
        if (
            request.provider_profile == "precision_keyframes"
            and conditioning_prompt.startswith("KEYFRAME ALIGNMENT:")
        ):
            _, _, conditioning_prompt = conditioning_prompt.partition("\n\n")
        prompt["136"]["inputs"]["prompt"] = _compile_h3_prompt(
            request,
            conditioning_prompt,
        )
        output_prefix = f"video/autodl_{fingerprint[:16]}"
        prompt["92"]["inputs"]["filename_prefix"] = output_prefix
        return replace(
            legacy,
            prompt=prompt,
            fingerprint=fingerprint,
            output_prefix=output_prefix,
            uploads=uploads,
        )


def compiled_workflow_evidence(compiled: CompiledWorkflow) -> dict[str, Any]:
    compiler_source = Path(__file__)
    manifest = {
        "compiler": "AutoDLWorkflowCompiler",
        "workflow_version": WORKFLOW_VERSION,
        "profile": compiled.profile,
        "profile_version": compiled.profile_version,
        "deployment_gate": compiled.deployment_gate,
        "logic_source": compiler_source.name,
        "logic_sha256": _sha256_file(compiler_source),
    }
    payload = {
        "fingerprint_scheme": FINGERPRINT_SCHEME,
        "request_fingerprint": compiled.fingerprint,
        "compiled_workflow_sha256": _canonical_sha256(compiled.prompt),
        "compiler_manifest": manifest,
    }
    return {**payload, "execution_fingerprint": _canonical_sha256(payload)}


def final_conditioning_evidence(compiled: CompiledWorkflow) -> dict[str, str]:
    """Describe the exact final Comfy conditioning for read-only audit export.

    The exported value is obtained only after the AutoDL workflow has compiled
    the immutable stage-two generation script into MiniMax's FL2VA/Ref2VA
    structure.  It must never be presented as the stage-two script itself.
    """

    conditioning = extract_final_h3_conditioning(compiled)
    return {
        "source": "compiled_workflow.prompt[136].inputs.prompt",
        "conditioning": conditioning,
        "final_conditioning_sha256": hashlib.sha256(
            conditioning.encode("utf-8")
        ).hexdigest(),
    }


def _replace_values(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _replace_values(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_values(item, replacements) for item in value]
    if isinstance(value, str):
        return replacements.get(value, value)
    return value


def _compile_h3_prompt(request: H3Request, source_prompt: str) -> str:
    """Apply MiniMax's official Ref2VA or FL2VA prompt structure locally."""

    source_prompt, explicit_sfx = _split_inline_audio(source_prompt.strip())
    if request.provider_profile == "fast":
        return _compile_ref2va_prompt(request, source_prompt, explicit_sfx)
    return _compile_fl2va_prompt(request, source_prompt, explicit_sfx)


def _compile_ref2va_prompt(
    request: H3Request, source_prompt: str, explicit_sfx: str | None
) -> str:
    definitions: list[str] = []
    retention: list[str] = []
    labels: list[str] = []
    for index, asset in enumerate(request.media, start=1):
        label = f"<Picture {index}>"
        labels.append(label)
        name = asset.prompt_label or f"ordered approved storyboard reference {index}"
        role = (asset.semantic_role or "storyboard").replace("_", " ")
        definitions.append(
            f"{label} is {name}, an ordered {role} reference for the target video."
        )

        preserve = ", ".join(asset.must_preserve)
        may_change = ", ".join(asset.may_change)
        relationship = (
            f"Preserve {preserve}."
            if preserve
            else "Preserve its approved visual content."
        )
        if may_change:
            relationship += f" Only {may_change} may change as the sequence moves."
        retention.append(
            f"{label} (ordered storyboard reference): fully_preserved - {relationship}"
        )

    joined_labels = ", ".join(labels)
    soundscape, music = _audio_sections(
        request.audio_policy,
        "detailed_description",
        explicit_sfx,
    )
    description = _ensure_first_shot(source_prompt)
    return (
        "subject_definitions:\n"
        + "\n".join(definitions)
        + "\n\nsummary:\n"
        + f"[reference generation] The target video is one continuous {request.duration}-second "
        + f"sequence generated from {joined_labels} in the supplied order. The requested "
        + "action, camera, timing, dialogue, visible text, and sound are specified below.\n\n"
        + "retention_analysis:\n"
        + "\n".join(retention)
        + "\n\ndetailed_description:\n"
        + f"The target video follows {joined_labels} as approved visual references in their "
        + "supplied order.\n"
        + f"{description}\n\n"
        + f"overall_soundscape:\n{soundscape}\n\n"
        + f"non_diegetic_music:\n{music}"
    )


def _compile_fl2va_prompt(
    request: H3Request, source_prompt: str, explicit_sfx: str | None
) -> str:
    count = len(request.media)
    explicit_positions = [
        asset.frame_index is not None or asset.anchor_time_ms is not None
        for asset in request.media
    ]
    if any(explicit_positions) and not all(explicit_positions):
        raise H3InputError(
            "precision keyframes cannot mix timed and untimed storyboard anchors"
        )
    if all(explicit_positions):
        seconds = tuple(
            (
                float(asset.frame_index) / 24
                if asset.frame_index is not None
                else float(asset.anchor_time_ms) / 1000
            )
            for asset in request.media
        )
    elif count == 1:
        seconds = (0.0,)
    else:
        seconds = tuple(
            index * request.duration / (count - 1) for index in range(count)
        )
    alignment = "; ".join(
        f"Picture {index} aligns with the {second:.2f}-second mark of the target video"
        for index, second in enumerate(seconds, start=1)
    )
    labels = tuple(f"<Picture {index}>" for index in range(1, count + 1))
    visual_path = f"from {labels[0]} to {labels[-1]}"
    if count > 2:
        visual_path = (
            f"from {labels[0]} through {', '.join(labels[1:-1])} to {labels[-1]}"
        )
    soundscape, music = _audio_sections(
        request.audio_policy,
        "integrated_multimodal_description",
        explicit_sfx,
    )
    description = _ensure_first_shot(source_prompt)
    return (
        f"How the reference pictures align with the target video — {alignment}.\n\n"
        + "integrated_multimodal_description: "
        + f"The ordered keyframes {visual_path} anchor one timed target video; reach each "
        + f"approved state at its aligned time. {description}\n\n"
        + f"overall_soundscape: {soundscape}\n\n"
        + f"non_diegetic_music: {music}"
    )


def _ensure_first_shot(source_prompt: str) -> str:
    if re.search(r"\[Shot\s+1\]", source_prompt, flags=re.IGNORECASE):
        return source_prompt
    return f"[Shot 1] {source_prompt}"


def _split_inline_audio(source_prompt: str) -> tuple[str, str | None]:
    match = re.search(
        r"(?:^|\n)同步音效[:：]\s*(.+?)(?:[;；]\s*SFX-only)?(?:。|\n|$)",
        source_prompt,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match is not None:
        body = source_prompt[: match.start()].rstrip()
        sfx = match.group(1).strip(" ,，、;；。")
        return body, sfx or None
    silence = re.search(r"(?:^|\n)全程静音[^\n]*$", source_prompt)
    if silence is not None:
        return source_prompt[: silence.start()].rstrip(), None
    return source_prompt, None


def _audio_sections(
    audio_policy: str,
    description_field: str,
    explicit_sfx: str | None,
) -> tuple[str, str]:
    if audio_policy == "silent":
        return ("Mute", "N/A")
    if audio_policy == "sfx_only":
        concrete = f"{explicit_sfx}. " if explicit_sfx else ""
        return (
            concrete
            + "Only these synchronized diegetic environmental and visible physical-action "
            + "sounds are audible. No dialogue, narration, voice, singing, music, or off-screen "
            + "sound. Do not infer speech from text or reference images; use silence when no "
            + f"sound is specified in {description_field}.",
            "N/A",
        )
    soundscape = (
        "Only the dialogue and synchronized diegetic environmental and physical action sounds "
        f"explicitly scripted in {description_field} are audible. Do not add unscripted voices "
        "or unrequested sounds."
    )
    return (
        soundscape,
        "Use only the non-diegetic music explicitly scripted in "
        f"{description_field}; do not add any other music.",
    )


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
