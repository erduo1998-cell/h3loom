"""Read-only stage router for the SRT-to-B-roll workflow."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

from .requests import load_request
from .h3.models import H3InputError
from .h3.prompt_gate import validate_h3_motion_prompt
from .task import (
    GOLD_PRODUCTION_CONTRACT,
    THREE_STAGE_WORKFLOW_CONTRACT,
    BrollTaskError,
    BrollTaskStore,
    sha256_file,
    task_provider,
)


_GENERATION_IMAGE_ROLES = {"reference_image", "first_frame", "last_frame"}
_ADDITIONAL_REFERENCE_ROLES = {"reference_video", "reference_audio"}
_PROVIDER_PROFILES = {
    "fast", "precision_keyframes", "ref_multimodal", "fl2v_explicit",
    "precision_timed", "precision_timed_h3keyframes",
    "refine_2pass_exp", "refine_2pass_int8_exp",
}
_SHOT_SIZES = {
    "extreme_wide",
    "wide",
    "full",
    "medium_wide",
    "medium",
    "medium_close",
    "close_up",
    "extreme_close_up",
    "insert",
}
_CAMERA_ANGLES = {
    "eye_level",
    "high_angle",
    "low_angle",
    "overhead",
    "birds_eye",
    "ground_level",
    "dutch_angle",
}
def _validate_frozen_h3_prompt(
    shot_id: str,
    prompt: Any,
    *,
    anchor_count: int,
    audio_policy: str,
) -> None:
    try:
        validate_h3_motion_prompt(
            prompt,
            anchor_count=anchor_count,
            audio_policy=audio_policy,
            label=f"{shot_id} frozen H3 generation script",
        )
    except H3InputError as exc:
        raise BrollTaskError(str(exc)) from exc


def validate_visual_lock(
    directory: Path, task: Mapping[str, Any], payload: Mapping[str, Any]
) -> None:
    """Require both visual authorities before any scene or camera planning."""

    if payload.get("task_id") != task.get("task_id"):
        raise BrollTaskError("visual lock belongs to a different task")
    source_binding = payload.get("task_source_binding")
    frozen_source = task.get("source", {})
    expected_input_hashes = [
        str(item.get("sha256", ""))
        for item in frozen_source.get("inputs", [])
        if isinstance(item, Mapping)
    ]
    if (
        not isinstance(source_binding, Mapping)
        or source_binding.get("annotations_applied")
        != list(frozen_source.get("annotations", []))
        or source_binding.get("input_sha256s_applied") != expected_input_hashes
        or source_binding.get("forbidden_applied")
        != list(frozen_source.get("forbidden", []))
        or not str(source_binding.get("existing_design_scope", "")).strip()
    ):
        raise BrollTaskError(
            "visual lock must preserve the task's frozen annotations, inputs, existing design scope and forbidden list"
        )
    references = payload.get("references")
    if not isinstance(references, Mapping):
        raise BrollTaskError("visual lock requires two classified reference groups")
    for role in ("content_scene_style", "talking_head_transition"):
        items = references.get(role)
        if not isinstance(items, list) or not items:
            raise BrollTaskError(f"visual lock requires {role} references")
        for item in items:
            if not isinstance(item, Mapping):
                raise BrollTaskError(f"visual lock {role} reference must be an object")
            if not all(str(item.get(field, "")).strip() for field in ("source", "sha256", "scope")):
                raise BrollTaskError(
                    f"visual lock {role} reference requires source, sha256 and scope"
                )
            if not re.fullmatch(r"[a-f0-9]{64}", str(item["sha256"])):
                raise BrollTaskError(f"visual lock {role} reference has an invalid SHA-256")
            relative = item.get("path")
            if relative is not None:
                path = _inside(directory, str(relative))
                if not path.is_file() or sha256_file(path) != item["sha256"]:
                    raise BrollTaskError(
                        f"visual lock {role} local reference is missing or changed"
                    )
    decisions = payload.get("decisions")
    required = {
        "subject_language",
        "material_language",
        "space_language",
        "character_scale_proportion",
        "palette_exposure_lighting",
        "contrast_density",
        "camera_language",
        "variation_rule",
        "talking_head_transition",
        "forbidden_elements",
    }
    if not isinstance(decisions, Mapping) or required - set(decisions):
        raise BrollTaskError("visual lock lacks scene/style/transition decisions")
    for field in required - {"forbidden_elements"}:
        if not str(decisions.get(field, "")).strip():
            raise BrollTaskError(f"visual lock decision {field} must not be empty")
    forbidden = decisions.get("forbidden_elements")
    if not isinstance(forbidden, list):
        raise BrollTaskError("visual lock forbidden_elements must be a list")
    review = directory / "visual-lock.md"
    if not review.is_file() or not review.read_text(encoding="utf-8").strip():
        raise BrollTaskError("visual-lock.md is missing or empty")


def validate_storyboard_board_plan(
    directory: Path,
    task: Mapping[str, Any],
    payload: Mapping[str, Any],
    shot_plan: Mapping[str, Any],
) -> None:
    """Freeze semantic board count before the first Imagine call."""

    if payload.get("task_id") != task.get("task_id"):
        raise BrollTaskError("storyboard board plan belongs to a different task")
    planned = [str(item["shot_id"]) for item in shot_plan["shots"]]
    shots = payload.get("shots")
    if not isinstance(shots, list) or [str(item.get("shot_id", "")) for item in shots] != planned:
        raise BrollTaskError("storyboard board plan must match the shot plan order")
    plan_by_id = {str(item["shot_id"]): item for item in shot_plan["shots"]}
    for item in shots:
        shot_id = str(item["shot_id"])
        count = item.get("board_count")
        groups = item.get("semantic_groups")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 4:
            raise BrollTaskError(f"{shot_id} board_count must be 1-4")
        if not str(item.get("reason", "")).strip():
            raise BrollTaskError(f"{shot_id} board count requires a semantic reason")
        if not isinstance(groups, list) or len(groups) != count:
            raise BrollTaskError(f"{shot_id} semantic_groups must match board_count")
        previous_end = 0.0
        for index, group in enumerate(groups, start=1):
            if not isinstance(group, Mapping) or group.get("board_number") != index:
                raise BrollTaskError(f"{shot_id} board numbers must be consecutive")
            start = float(group.get("start_seconds", -1))
            end = float(group.get("end_seconds", -1))
            if abs(start - previous_end) > 0.05 or end <= start:
                raise BrollTaskError(
                    f"{shot_id} board semantic groups must be contiguous and non-empty"
                )
            if not str(group.get("semantic_purpose", "")).strip():
                raise BrollTaskError(f"{shot_id} board group requires semantic_purpose")
            previous_end = end
        planned_shot = plan_by_id[shot_id]
        source_span = float(planned_shot["source_end_seconds"]) - float(
            planned_shot["source_start_seconds"]
        )
        if abs(previous_end - source_span) > 0.25:
            raise BrollTaskError(f"{shot_id} board plan must cover the selected source span")


def _inside(directory: Path, value: str) -> Path:
    target = (directory / value).resolve()
    try:
        target.relative_to(directory.resolve())
    except ValueError as exc:
        raise BrollTaskError(f"artifact path escapes task directory: {value}") from exc
    return target


def _review_bundle_sha256(artifacts: list[dict[str, str]]) -> str:
    serialized = json.dumps(
        artifacts, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _frozen_artifact(directory: Path, role: str, relative: str) -> dict[str, str]:
    path = _inside(directory, relative)
    if not path.is_file() or path.stat().st_size == 0:
        raise BrollTaskError(f"approval artifact is missing or empty: {relative}")
    return {
        "role": role,
        "path": relative,
        "sha256": sha256_file(path),
    }


def _shot_plan_approval_required(
    task: Mapping[str, Any], shot_plan: Mapping[str, Any]
) -> bool:
    approval = task.get("shot_plan_approval")
    return (
        task.get("spec", {}).get("workflow_contract")
        == THREE_STAGE_WORKFLOW_CONTRACT
    ) or (
        isinstance(approval, Mapping) and approval.get("status") != "not_required"
    ) or shot_plan.get("schema_version") == "3.0"


def validate_approved_generate_set(
    task: Mapping[str, Any],
    shot_ids: list[str],
    *,
    context: str,
) -> None:
    """Prove that the approved generation set and an actual shot set are closed."""

    if len(shot_ids) != len(set(shot_ids)) or any(not value for value in shot_ids):
        raise BrollTaskError(f"{context} contains duplicate or empty shot ids")
    policy = task.get("inheritance_policy")
    ledger = task.get("variant_ledger")
    if policy is None and ledger is None:
        return
    if not isinstance(policy, Mapping) or not isinstance(ledger, Mapping):
        raise BrollTaskError("task inheritance policy or variant ledger is unreadable")
    approved = ledger.get("approved_generate_set")
    if not isinstance(approved, list):
        raise BrollTaskError("variant ledger lacks approved_generate_set")
    if not approved:
        approval = task.get("shot_plan_approval")
        if (
            policy.get("mode") == "fresh_redesign"
            and isinstance(approval, Mapping)
            and approval.get("status") == "not_required"
        ):
            return
        raise BrollTaskError("approved generate set is empty; approve the shot plan first")
    if set(str(value) for value in approved) != set(shot_ids):
        raise BrollTaskError(
            f"approved generate set is not closed over the actual {context} shots"
        )


def shot_plan_approval_snapshot(
    directory: Path,
    task: Mapping[str, Any],
    *,
    visual_lock: Mapping[str, Any],
    shot_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Freeze the exact JSON and human-readable stage-1 review bundle."""

    validate_visual_lock(directory, task, visual_lock)
    validate_shot_plan(task, shot_plan)
    artifacts = [
        _frozen_artifact(directory, "visual_lock_json", "visual-lock.json"),
        _frozen_artifact(directory, "visual_lock_review", "visual-lock.md"),
        _frozen_artifact(directory, "shot_plan_json", "shot-plan.json"),
        _frozen_artifact(directory, "shot_plan_review", "shot-plan.md"),
    ]
    inheritance_snapshot = {
        "inheritance_policy": task.get("inheritance_policy"),
        "variant_ledger": task.get("variant_ledger"),
    }
    inheritance_sha256 = hashlib.sha256(
        json.dumps(
            inheritance_snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "approval_scope": "visual_lock_and_shot_plan",
        "review_bundle_sha256": _review_bundle_sha256(artifacts),
        "inheritance_ledger_sha256": inheritance_sha256,
        "approved_generate_set": list(
            task.get("variant_ledger", {}).get("approved_generate_set", [])
        ),
        "artifacts": artifacts,
    }


def validate_shot_plan_approval(
    task: Mapping[str, Any], directory: Path, shot_plan: Mapping[str, Any]
) -> None:
    if not _shot_plan_approval_required(task, shot_plan):
        return
    approval = task.get("shot_plan_approval")
    if not isinstance(approval, Mapping) or approval.get("status") != "approved":
        raise BrollTaskError(
            "visual lock and shot plan require explicit user approval before storyboards"
        )
    if approval.get("approval_source") != "explicit_user_instruction":
        raise BrollTaskError("shot-plan approval is not backed by an explicit user instruction")
    try:
        visual_lock = json.loads(
            (directory / "visual-lock.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise BrollTaskError("approved visual lock is missing or unreadable") from exc
    current = shot_plan_approval_snapshot(
        directory, task, visual_lock=visual_lock, shot_plan=shot_plan
    )
    for field in (
        "approval_scope",
        "review_bundle_sha256",
        "inheritance_ledger_sha256",
        "approved_generate_set",
        "artifacts",
    ):
        if approval.get(field) != current[field]:
            raise BrollTaskError(
                "visual lock or shot plan changed after approval; approve-shot-plan again"
            )


def validate_shot_plan(task: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    if payload.get("task_id") != task.get("task_id"):
        raise BrollTaskError("shot plan belongs to a different task")
    if not str(payload.get("source_thesis", "")).strip():
        raise BrollTaskError("shot plan must record the full-script thesis")
    if not str(payload.get("audience_start", "")).strip():
        raise BrollTaskError("shot plan must record the audience starting point")
    strict = (
        task.get("spec", {}).get("workflow_contract")
        == THREE_STAGE_WORKFLOW_CONTRACT
    )
    structured = payload.get("schema_version") == "3.0"
    if strict and not structured:
        raise BrollTaskError(
            "three-stage-four-panel-v1 requires shot-plan schema_version 3.0"
        )
    approval = task.get("shot_plan_approval")
    if (
        isinstance(approval, Mapping)
        and approval.get("status") in {"pending", "approved"}
        and not structured
    ):
        raise BrollTaskError(
            "deterministic shot-plan approval requires schema_version 3.0"
        )
    if strict:
        for field in (
            "source_duration_seconds",
            "coverage_target_percent",
            "selected_broll_duration_seconds",
            "actual_coverage_percent",
        ):
            if isinstance(payload.get(field), bool) or not isinstance(
                payload.get(field), (int, float)
            ):
                raise BrollTaskError(f"three-stage shot plan requires numeric {field}")
        source_duration = float(payload["source_duration_seconds"])
        target_coverage = float(payload["coverage_target_percent"])
        if source_duration <= 0 or not 0 < target_coverage <= 100:
            raise BrollTaskError("shot plan duration and coverage target are invalid")
    shots = payload.get("shots")
    if not isinstance(shots, list) or not shots:
        raise BrollTaskError("shot plan must contain selected B-roll segments")
    required = {
        "shot_id",
        "source_range",
        "source_quote",
        "visual_job",
        "scene_and_reason",
        "style_route",
        "beats",
        "transitions",
        "continuity_anchor",
        "necessary_text",
        "sound_intent",
        "generation_duration",
    }
    seen: set[str] = set()
    selected_ranges: list[tuple[float, float]] = []
    for shot in shots:
        if not isinstance(shot, Mapping):
            raise BrollTaskError("each shot must be an object")
        missing = sorted(required - set(shot))
        if missing:
            raise BrollTaskError(f"shot is missing fields: {', '.join(missing)}")
        shot_id = str(shot["shot_id"])
        if not shot_id or shot_id in seen:
            raise BrollTaskError(f"duplicate/empty shot id: {shot_id}")
        seen.add(shot_id)
        duration = shot["generation_duration"]
        if isinstance(duration, bool) or not isinstance(duration, int) or not 4 <= duration <= 15:
            raise BrollTaskError(f"{shot_id} generation duration must be 4-15 seconds")
        if not isinstance(shot["beats"], list) or not shot["beats"]:
            raise BrollTaskError(f"{shot_id} must contain semantic beats")
        necessary_text = shot.get("necessary_text")
        if (
            not isinstance(necessary_text, list)
            or any(not isinstance(value, str) or not value.strip() for value in necessary_text)
            or len(necessary_text) != len(set(necessary_text))
        ):
            raise BrollTaskError(
                f"{shot_id} necessary_text must contain unique non-empty strings or be []"
            )
        if strict:
            _validate_three_stage_shot(
                shot_id, shot, selected_ranges, structured=structured
            )
    if strict:
        selected_ranges.sort()
        for previous, current in zip(selected_ranges, selected_ranges[1:]):
            if current[0] < previous[1] - 0.001:
                raise BrollTaskError("selected B-roll source ranges must not overlap")
        selected_seconds = sum(end - start for start, end in selected_ranges)
        actual_coverage = selected_seconds / source_duration * 100
        if abs(selected_seconds - float(payload["selected_broll_duration_seconds"])) > 0.05:
            raise BrollTaskError("selected B-roll seconds do not match the source ranges")
        if abs(actual_coverage - float(payload["actual_coverage_percent"])) > 0.05:
            raise BrollTaskError("actual B-roll coverage does not match the source ranges")
    if structured:
        _validate_rhetorical_coverage(payload.get("rhetorical_coverage"), seen)


def _validate_rhetorical_coverage(value: Any, shot_ids: set[str]) -> None:
    """Require every declared essential chapter/member to map to an active shot."""

    if not isinstance(value, list):
        raise BrollTaskError("schema 3.0 shot plan requires rhetorical_coverage[]")
    seen_members: set[str] = set()
    allowed_roles = {"chapter", "problem", "callback", "classification", "other"}
    for item in value:
        if not isinstance(item, Mapping):
            raise BrollTaskError("rhetorical_coverage entries must be objects")
        member_id = str(item.get("member_id", "")).strip()
        label = str(item.get("label", "")).strip()
        role = item.get("role")
        required = item.get("required")
        covered = item.get("covered_shot_ids")
        if (
            re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", member_id) is None
            or member_id in seen_members
            or not label
            or role not in allowed_roles
            or not isinstance(required, bool)
            or not isinstance(covered, list)
            or len(covered) != len(set(covered))
            or any(not isinstance(shot_id, str) or not shot_id for shot_id in covered)
        ):
            raise BrollTaskError("rhetorical_coverage entry is invalid or duplicated")
        if required and not covered:
            raise BrollTaskError(
                f"required rhetorical member {member_id} has no covered shot"
            )
        unknown = set(covered) - shot_ids
        if unknown:
            raise BrollTaskError(
                f"rhetorical member {member_id} references unknown shots: {sorted(unknown)}"
            )
        seen_members.add(member_id)


def _validate_three_stage_shot(
    shot_id: str,
    shot: Mapping[str, Any],
    selected_ranges: list[tuple[float, float]],
    *,
    structured: bool,
) -> None:
    for field in ("source_start_seconds", "source_end_seconds"):
        if isinstance(shot.get(field), bool) or not isinstance(
            shot.get(field), (int, float)
        ):
            raise BrollTaskError(f"{shot_id} requires numeric {field}")
    start = float(shot["source_start_seconds"])
    end = float(shot["source_end_seconds"])
    source_span = end - start
    if start < 0 or not 0 < source_span <= 15:
        raise BrollTaskError(f"{shot_id} source span must be within 0-15 seconds")
    selected_ranges.append((start, end))
    if int(shot["generation_duration"]) != max(4, math.ceil(source_span - 0.001)):
        raise BrollTaskError(
            f"{shot_id} generation duration must be the 4-15 second ceiling of its source span"
        )
    if shot.get("text_strategy") not in {
        "none",
        "keyword",
        "concept_ui",
        "exact_ai_text",
    }:
        raise BrollTaskError(f"{shot_id} requires a valid AI-only text_strategy")
    scene = shot.get("scene_design")
    scene_required = {
        "subject",
        "setting",
        "visual_style_application",
        "talking_head_transition",
    }
    if structured:
        scene_required.add("visual_progress")
    if not isinstance(scene, Mapping) or scene_required - set(scene):
        raise BrollTaskError(f"{shot_id} requires scene_design before camera planning")
    if not all(str(scene[field]).strip() for field in scene_required):
        raise BrollTaskError(f"{shot_id} scene_design fields must not be empty")
    beat_required = {
        "time",
        "start_seconds",
        "end_seconds",
        "spoken_addition",
        "shot_number",
        "framing",
        "camera",
        "transition_in",
    }
    if structured:
        if shot.get("sequence_mode") not in {"multi_shot", "one_take"}:
            raise BrollTaskError(
                f"{shot_id} requires sequence_mode=multi_shot or one_take"
            )
        beat_required.update(
            {"visual_content", "shot_size", "camera_angle", "viewpoint"}
        )
    previous_end = 0.0
    previous_shot = 0
    previous_signature: tuple[str, str, str] | None = None
    for index, beat in enumerate(shot["beats"]):
        if not isinstance(beat, Mapping):
            raise BrollTaskError(f"{shot_id} beat {index + 1} must be an object")
        missing = sorted(beat_required - set(beat))
        if missing:
            raise BrollTaskError(
                f"{shot_id} beat {index + 1} is missing: {', '.join(missing)}"
            )
        beat_start = float(beat["start_seconds"])
        beat_end = float(beat["end_seconds"])
        if beat_start < previous_end - 0.001 or beat_end <= beat_start:
            raise BrollTaskError(f"{shot_id} beat times must be ordered and non-empty")
        shot_number = int(beat["shot_number"])
        transition = str(beat["transition_in"])
        signature = (
            str(beat.get("shot_size", "")).strip(),
            str(beat.get("camera_angle", "")).strip(),
            str(beat.get("viewpoint", "")).strip(),
        )
        if structured and (
            signature[0] not in _SHOT_SIZES
            or signature[1] not in _CAMERA_ANGLES
            or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", signature[2]) is None
        ):
            raise BrollTaskError(
                f"{shot_id} beat requires categorical shot_size/camera_angle/viewpoint"
            )
        if structured and shot.get("sequence_mode") == "one_take" and shot_number != 1:
            raise BrollTaskError(
                f"{shot_id} one_take explicitly permits only Shot 1 with continue beats"
            )
        if index == 0:
            if abs(beat_start) > 0.05 or shot_number != 1 or transition != "start":
                raise BrollTaskError(
                    f"{shot_id} must begin at 0 with Shot 1 and transition_in=start"
                )
        elif shot_number == previous_shot:
            if transition != "continue":
                raise BrollTaskError(
                    f"{shot_id} repeated shot_number requires transition_in=continue"
                )
        elif shot_number == previous_shot + 1:
            if transition not in {"cut", "match_cut", "occlusion_cut"}:
                raise BrollTaskError(f"{shot_id} new shot requires a cut transition")
            if structured and signature == previous_signature:
                raise BrollTaskError(
                    f"{shot_id} new shot must change shot_size, camera_angle or viewpoint"
                )
        else:
            raise BrollTaskError(
                f"{shot_id} shot_number must stay the same or advance by one"
            )
        if not all(
            str(beat[field]).strip()
            for field in (
                "time",
                "spoken_addition",
                "framing",
                "camera",
                *(("visual_content",) if structured else ()),
            )
        ):
            raise BrollTaskError(f"{shot_id} beat fields must not be empty")
        previous_end = beat_end
        previous_shot = shot_number
        previous_signature = signature
    if abs(previous_end - source_span) > 0.25:
        raise BrollTaskError(f"{shot_id} beats must cover the selected source span")


def validate_storyboard_manifest(
    directory: Path,
    payload: Mapping[str, Any],
    *,
    require_h3_prompts: bool = True,
) -> None:
    task = json.loads((directory / "task.json").read_text(encoding="utf-8"))
    if payload.get("task_id") != task.get("task_id"):
        raise BrollTaskError("storyboard manifest belongs to a different task")
    if payload.get("generator") != "codex-imagine":
        raise BrollTaskError("storyboards must be generated by Codex Imagine")
    shots = payload.get("shots")
    if not isinstance(shots, list) or not shots:
        raise BrollTaskError("storyboard manifest has no shots")
    try:
        visual_lock = json.loads((directory / "visual-lock.json").read_text(encoding="utf-8"))
        plan = json.loads((directory / "shot-plan.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BrollTaskError("storyboards require a valid visual lock and shot plan") from exc
    validate_visual_lock(directory, task, visual_lock)
    validate_shot_plan(task, plan)
    planned_ids = [str(item.get("shot_id", "")) for item in plan.get("shots", [])]
    planned_by_id = {str(item.get("shot_id", "")): item for item in plan.get("shots", [])}
    manifest_ids = [str(item.get("shot_id", "")) for item in shots if isinstance(item, Mapping)]
    validate_shot_plan_approval(task, directory, plan)
    validate_approved_generate_set(task, planned_ids, context="shot plan")
    validate_approved_generate_set(task, manifest_ids, context="storyboard manifest")
    if manifest_ids != planned_ids:
        raise BrollTaskError("storyboard manifest order/shot ids differ from the shot plan")
    contract = task.get("spec", {}).get("production_contract")
    strict_storyboards = (
        task.get("spec", {}).get("workflow_contract")
        == THREE_STAGE_WORKFLOW_CONTRACT
    )
    if strict_storyboards and payload.get("schema_version") != "3.0":
        raise BrollTaskError(
            "three-stage-four-panel-v1 requires storyboard manifest schema_version 3.0"
        )
    board_plan_by_id: dict[str, Mapping[str, Any]] = {}
    if strict_storyboards:
        try:
            board_plan = json.loads(
                (directory / "storyboard-board-plan.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise BrollTaskError("three-stage storyboards require storyboard-board-plan.json") from exc
        validate_storyboard_board_plan(directory, task, board_plan, plan)
        board_plan_by_id = {str(item["shot_id"]): item for item in board_plan["shots"]}
    if contract == GOLD_PRODUCTION_CONTRACT:
        sample_payload = _validated_approved_storyboard_sample(task, directory, plan)
        guard = payload.get("h3_visual_guard")
        if not isinstance(guard, str) or not 40 <= len(guard.strip()) <= 650:
            raise BrollTaskError(
                "gold storyboard manifest requires a 40-650 character h3_visual_guard"
            )
    else:
        sample_payload = None
    total_generation_images = 0
    for shot in shots:
        if not isinstance(shot, Mapping) or not str(shot.get("shot_id", "")).strip():
            raise BrollTaskError("storyboard shot requires shot_id")
        boards = shot.get("boards")
        if strict_storyboards and boards is None:
            raise BrollTaskError("three-stage workflow requires boards[] for every shot")
        if boards is not None:
            _validate_four_panel_boards(
                directory,
                str(shot["shot_id"]),
                boards,
                planned_by_id[str(shot["shot_id"])],
                board_plan_by_id.get(str(shot["shot_id"])),
                structured=plan.get("schema_version") == "3.0",
            )
            if strict_storyboards and len(boards) != int(
                board_plan_by_id[str(shot["shot_id"])]["board_count"]
            ):
                raise BrollTaskError(
                    f"{shot['shot_id']} generated board count differs from the frozen semantic plan"
                )
        else:
            review = _inside(directory, str(shot.get("review_board", "")))
            if not review.is_file():
                raise BrollTaskError(f"review board is missing: {review}")
        images = shot.get("generation_images")
        if not isinstance(images, list):
            raise BrollTaskError("each shot needs clean generation images")
        if contract == GOLD_PRODUCTION_CONTRACT and not 3 <= len(images) <= 5:
            raise BrollTaskError("gold production requires exactly 3-5 H3 anchor images per shot")
        if contract != GOLD_PRODUCTION_CONTRACT and not 1 <= len(images) <= 9:
            raise BrollTaskError("each shot needs 1-9 clean generation images")
        total_generation_images += len(images)
        for value in images:
            image = _inside(directory, str(value))
            if not image.is_file() or image.stat().st_size == 0:
                raise BrollTaskError(f"generation storyboard is missing/empty: {image}")
        if strict_storyboards:
            anchor_times = shot.get("generation_anchor_times_seconds")
            if (
                not isinstance(anchor_times, list)
                or len(anchor_times) != len(images)
                or any(
                    isinstance(value, bool) or not isinstance(value, (int, float))
                    for value in anchor_times
                )
            ):
                raise BrollTaskError(
                    f"{shot['shot_id']} requires one semantic time for every H3 anchor"
                )
            source_span = float(planned_by_id[str(shot["shot_id"])]["source_end_seconds"]) - float(
                planned_by_id[str(shot["shot_id"])]["source_start_seconds"]
            )
            normalized_times = [float(value) for value in anchor_times]
            if (
                normalized_times != sorted(normalized_times)
                or abs(normalized_times[0]) > 0.05
                or abs(normalized_times[-1] - source_span) > 0.05
                or len(set(normalized_times)) != len(normalized_times)
            ):
                raise BrollTaskError(
                    f"{shot['shot_id']} H3 anchor times must be unique, ordered, and span 0 to the source end"
                )
            if require_h3_prompts:
                _validate_frozen_h3_prompt(
                    str(shot["shot_id"]),
                    shot.get("h3_request_prompt"),
                    anchor_count=len(images),
                    audio_policy=str(task.get("spec", {}).get("audio_policy", "")),
                )
    if contract == GOLD_PRODUCTION_CONTRACT:
        maximum = math.ceil(4.1 * len(shots))
        if total_generation_images > maximum:
            raise BrollTaskError(
                f"gold production anchor density exceeds {maximum} images for {len(shots)} shots"
            )
        _require_sample_unchanged_in_full_manifest(directory, sample_payload, payload)
    _approved_reference_assets(directory, payload, set(planned_ids))


def _validate_four_panel_boards(
    directory: Path,
    shot_id: str,
    boards: Any,
    planned_shot: Mapping[str, Any],
    board_plan: Mapping[str, Any] | None = None,
    *,
    structured: bool = False,
) -> None:
    if not isinstance(boards, list) or not 1 <= len(boards) <= 4:
        raise BrollTaskError(f"{shot_id} requires 1-4 four-panel storyboard boards")
    required_panel = {
        "panel_number",
        "time",
        "start_seconds",
        "end_seconds",
        "spoken_addition",
        "shot_number",
        "framing",
        "camera",
        "transition_in",
        "continuity_anchor",
        "text_strategy",
    }
    if structured:
        required_panel.update(
            {
                "visual_content",
                "shot_size",
                "camera_angle",
                "viewpoint",
                "required_text",
            }
        )
    board_ids: set[str] = set()
    previous_end = 0.0
    previous_shot = 0
    previous_signature: tuple[str, str, str] | None = None
    transferred_required_text: set[str] = set()
    planned_required_text = planned_shot.get("necessary_text", [])
    if not isinstance(planned_required_text, list):
        raise BrollTaskError(f"{shot_id} necessary_text must be an array")
    semantic_groups = (
        board_plan.get("semantic_groups", [])
        if isinstance(board_plan, Mapping)
        else []
    )
    for board_index, board in enumerate(boards):
        if not isinstance(board, Mapping):
            raise BrollTaskError(f"{shot_id} storyboard board must be an object")
        board_id = str(board.get("board_id", "")).strip()
        if not board_id or board_id in board_ids:
            raise BrollTaskError(f"{shot_id} storyboard board_id is empty or duplicated")
        board_ids.add(board_id)
        imagine_prompt = ""
        for role in ("raw_board", "review_board", "imagine_prompt"):
            path = _inside(directory, str(board.get(role, "")))
            if not path.is_file() or path.stat().st_size == 0:
                raise BrollTaskError(f"{shot_id} {role} is missing/empty: {path}")
            if role == "imagine_prompt":
                imagine_prompt = path.read_text(encoding="utf-8")
                if not all(
                    f"Panel {number}" in imagine_prompt for number in range(1, 5)
                ):
                    raise BrollTaskError(
                        f"{shot_id} Imagine prompt must explicitly describe Panel 1-4"
                    )
        panels = board.get("panels")
        if not isinstance(panels, list) or len(panels) != 4:
            raise BrollTaskError(f"{shot_id} every storyboard board must contain exactly 4 panels")
        if [panel.get("panel_number") for panel in panels if isinstance(panel, Mapping)] != [
            1,
            2,
            3,
            4,
        ]:
            raise BrollTaskError(f"{shot_id} panel numbers must be exactly 1,2,3,4")
        if semantic_groups:
            group = semantic_groups[board_index]
            if (
                abs(float(panels[0].get("start_seconds", -1)) - float(group["start_seconds"])) > 0.05
                or abs(float(panels[-1].get("end_seconds", -1)) - float(group["end_seconds"])) > 0.05
            ):
                raise BrollTaskError(
                    f"{shot_id} board {board_index + 1} does not match its frozen semantic-group time boundary"
                )
        for panel in panels:
            missing = sorted(required_panel - set(panel))
            if missing:
                raise BrollTaskError(
                    f"{shot_id} storyboard panel is missing: {', '.join(missing)}"
                )
            panel_start = float(panel["start_seconds"])
            panel_end = float(panel["end_seconds"])
            if abs(panel_start - previous_end) > 0.05 or panel_end <= panel_start:
                raise BrollTaskError(
                    f"{shot_id} storyboard panels must form one contiguous semantic timeline"
                )
            shot_number = int(panel["shot_number"])
            transition = str(panel["transition_in"])
            signature = (
                str(panel.get("shot_size", "")).strip(),
                str(panel.get("camera_angle", "")).strip(),
                str(panel.get("viewpoint", "")).strip(),
            )
            if structured and (
                signature[0] not in _SHOT_SIZES
                or signature[1] not in _CAMERA_ANGLES
                or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", signature[2]) is None
            ):
                raise BrollTaskError(
                    f"{shot_id} storyboard panel requires categorical shot_size/camera_angle/viewpoint"
                )
            if (
                structured
                and planned_shot.get("sequence_mode") == "one_take"
                and shot_number != 1
            ):
                raise BrollTaskError(
                    f"{shot_id} one_take storyboard may only use Shot 1"
                )
            if previous_shot == 0:
                if shot_number != 1 or transition != "start":
                    raise BrollTaskError(
                        f"{shot_id} first storyboard panel must start Shot 1"
                    )
            elif shot_number == previous_shot:
                if transition != "continue":
                    raise BrollTaskError(
                        f"{shot_id} repeated storyboard shot requires continue"
                    )
            elif shot_number == previous_shot + 1:
                if transition not in {"cut", "match_cut", "occlusion_cut"}:
                    raise BrollTaskError(
                        f"{shot_id} new storyboard shot requires a cut transition"
                    )
                if structured and signature == previous_signature:
                    raise BrollTaskError(
                        f"{shot_id} new storyboard shot must change shot_size, camera_angle or viewpoint"
                    )
            else:
                raise BrollTaskError(
                    f"{shot_id} storyboard shot_number must stay or advance by one"
                )
            if panel.get("text_strategy") not in {
                "none",
                "keyword",
                "concept_ui",
                "exact_ai_text",
            }:
                raise BrollTaskError(f"{shot_id} storyboard panel has invalid text_strategy")
            visual_content = str(
                panel.get("visual_content", panel.get("action_result", ""))
            ).strip()
            if not visual_content:
                raise BrollTaskError(
                    f"{shot_id} storyboard panel requires visual_content"
                )
            if not all(
                str(panel[field]).strip()
                for field in (
                    "time",
                    "spoken_addition",
                    "framing",
                    "camera",
                    "continuity_anchor",
                )
            ):
                raise BrollTaskError(f"{shot_id} storyboard panel fields must not be empty")
            if structured:
                required_text = panel.get("required_text")
                if (
                    not isinstance(required_text, list)
                    or any(
                        not isinstance(value, str) or not value.strip()
                        for value in required_text
                    )
                    or len(required_text) != len(set(required_text))
                ):
                    raise BrollTaskError(
                        f"{shot_id} panel required_text must contain unique strings or be []"
                    )
                if not set(required_text).issubset(set(planned_required_text)):
                    raise BrollTaskError(
                        f"{shot_id} panel required_text contains text absent from shot necessary_text"
                    )
                marker = (
                    f"Panel {int(panel['panel_number'])} required_text: "
                    + json.dumps(
                        required_text,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                if marker not in imagine_prompt:
                    raise BrollTaskError(
                        f"{shot_id} Imagine prompt lacks the exact required_text marker for Panel {panel['panel_number']}"
                    )
                transferred_required_text.update(required_text)
            previous_end = panel_end
            previous_shot = shot_number
            previous_signature = signature
    source_span = float(planned_shot["source_end_seconds"]) - float(
        planned_shot["source_start_seconds"]
    )
    if abs(previous_end - source_span) > 0.25:
        raise BrollTaskError(f"{shot_id} storyboard panels must cover the selected source span")
    if structured and transferred_required_text != set(planned_required_text):
        raise BrollTaskError(
            f"{shot_id} necessary_text is not closed over panel required_text"
        )


def validate_storyboard_sample(directory: Path, payload: Mapping[str, Any]) -> None:
    """Validate the 1-2 representative boards that must be approved before full production."""

    try:
        task = json.loads((directory / "task.json").read_text(encoding="utf-8"))
        plan = json.loads((directory / "shot-plan.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BrollTaskError("storyboard sample requires a valid task and shot plan") from exc
    if task.get("spec", {}).get("production_contract") != GOLD_PRODUCTION_CONTRACT:
        raise BrollTaskError("storyboard sample gate belongs only to gold production")
    if (
        task.get("spec", {}).get("workflow_contract")
        == THREE_STAGE_WORKFLOW_CONTRACT
        and payload.get("schema_version") != "3.0"
    ):
        raise BrollTaskError(
            "three-stage-four-panel-v1 requires storyboard sample schema_version 3.0"
        )
    validate_shot_plan(task, plan)
    validate_shot_plan_approval(task, directory, plan)
    if payload.get("task_id") != task.get("task_id") or payload.get("generator") != "codex-imagine":
        raise BrollTaskError("storyboard sample belongs to another task or generator")
    shots = payload.get("shots")
    if not isinstance(shots, list) or not 1 <= len(shots) <= 2:
        raise BrollTaskError("gold production requires 1-2 representative storyboard samples")
    planned_ids = {str(item["shot_id"]) for item in plan["shots"]}
    planned_by_id = {str(item["shot_id"]): item for item in plan["shots"]}
    strict_storyboards = (
        task.get("spec", {}).get("workflow_contract")
        == THREE_STAGE_WORKFLOW_CONTRACT
    )
    board_plan_by_id: dict[str, Mapping[str, Any]] = {}
    if strict_storyboards:
        try:
            visual_lock = json.loads(
                (directory / "visual-lock.json").read_text(encoding="utf-8")
            )
            board_plan = json.loads(
                (directory / "storyboard-board-plan.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise BrollTaskError(
                "three-stage storyboard sample requires visual lock and board plan"
            ) from exc
        validate_visual_lock(directory, task, visual_lock)
        validate_storyboard_board_plan(directory, task, board_plan, plan)
        board_plan_by_id = {
            str(item["shot_id"]): item for item in board_plan["shots"]
        }
    seen: set[str] = set()
    for shot in shots:
        if not isinstance(shot, Mapping):
            raise BrollTaskError("each storyboard sample must be an object")
        shot_id = str(shot.get("shot_id", ""))
        if shot_id not in planned_ids or shot_id in seen:
            raise BrollTaskError("storyboard sample has an unknown or duplicate shot id")
        seen.add(shot_id)
        boards = shot.get("boards")
        if strict_storyboards and boards is None:
            raise BrollTaskError("three-stage storyboard sample requires boards[]")
        if boards is not None:
            _validate_four_panel_boards(
                directory,
                shot_id,
                boards,
                planned_by_id[shot_id],
                board_plan_by_id.get(shot_id),
                structured=plan.get("schema_version") == "3.0",
            )
            if strict_storyboards and len(boards) != int(
                board_plan_by_id[shot_id]["board_count"]
            ):
                raise BrollTaskError(
                    f"{shot_id} sample board count differs from the frozen semantic plan"
                )
        else:
            review = _inside(directory, str(shot.get("review_board", "")))
            if not review.is_file() or review.stat().st_size == 0:
                raise BrollTaskError(f"storyboard sample review board is missing: {review}")
        images = shot.get("generation_images")
        if not isinstance(images, list) or not 3 <= len(images) <= 5:
            raise BrollTaskError("each gold storyboard sample requires 3-5 H3 anchor images")
        for value in images:
            image = _inside(directory, str(value))
            if not image.is_file() or image.stat().st_size == 0:
                raise BrollTaskError(f"storyboard sample image is missing/empty: {image}")
        if strict_storyboards:
            anchor_times = shot.get("generation_anchor_times_seconds")
            source_span = float(planned_by_id[shot_id]["source_end_seconds"]) - float(
                planned_by_id[shot_id]["source_start_seconds"]
            )
            if (
                not isinstance(anchor_times, list)
                or len(anchor_times) != len(images)
                or any(
                    isinstance(value, bool) or not isinstance(value, (int, float))
                    for value in anchor_times
                )
                or [float(value) for value in anchor_times]
                != sorted(float(value) for value in anchor_times)
                or abs(float(anchor_times[0])) > 0.05
                or abs(float(anchor_times[-1]) - source_span) > 0.05
            ):
                raise BrollTaskError(
                    f"{shot_id} storyboard sample requires ordered semantic anchor times"
                )


def storyboard_sample_approval_snapshot(
    directory: Path, payload: Mapping[str, Any]
) -> dict[str, Any]:
    validate_storyboard_sample(directory, payload)
    artifacts = _storyboard_artifacts(directory, payload)
    manifest_sha256 = sha256_file(directory / "storyboard-sample.json")
    review_bundle = [
        {
            "role": "storyboard_sample_manifest",
            "path": "storyboard-sample.json",
            "sha256": manifest_sha256,
        },
        *artifacts,
    ]
    return {
        "approval_scope": "representative_storyboard_sample",
        "review_bundle_sha256": _review_bundle_sha256(review_bundle),
        "manifest_sha256": manifest_sha256,
        "artifacts": artifacts,
    }


def _validated_approved_storyboard_sample(
    task: Mapping[str, Any], directory: Path, plan: Mapping[str, Any]
) -> Mapping[str, Any]:
    approval = task.get("storyboard_sample_approval")
    if not isinstance(approval, Mapping) or approval.get("status") != "approved":
        raise BrollTaskError(
            "approve 1-2 representative storyboard samples before generating the full set"
        )
    if (
        task.get("shot_plan_approval", {}).get("status") != "not_required"
        and approval.get("approval_source") != "explicit_user_instruction"
    ):
        raise BrollTaskError(
            "storyboard sample approval is not backed by an explicit user instruction"
        )
    try:
        sample = json.loads((directory / "storyboard-sample.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BrollTaskError("approved storyboard sample is missing or unreadable") from exc
    validate_storyboard_sample(directory, sample)
    current = storyboard_sample_approval_snapshot(directory, sample)
    if any(
        approval.get(field) != current[field]
        for field in (
            "approval_scope",
            "review_bundle_sha256",
            "manifest_sha256",
            "artifacts",
        )
    ):
        raise BrollTaskError("storyboard sample changed after approval; approve the sample again")
    return sample


def _require_sample_unchanged_in_full_manifest(
    directory: Path, sample: Mapping[str, Any] | None, full: Mapping[str, Any]
) -> None:
    if sample is None:
        raise BrollTaskError("gold production lacks an approved storyboard sample")
    full_by_id = {
        str(item["shot_id"]): item for item in full["shots"] if isinstance(item, Mapping)
    }
    for approved in sample["shots"]:
        shot_id = str(approved["shot_id"])
        current = full_by_id.get(shot_id)
        if (
            current is None
            or current.get("review_board") != approved.get("review_board")
            or current.get("boards") != approved.get("boards")
            or current.get("generation_images") != approved.get("generation_images")
            or current.get("generation_anchor_times_seconds")
            != approved.get("generation_anchor_times_seconds")
        ):
            raise BrollTaskError(
                f"{shot_id} differs from the representative storyboard sample the user approved"
            )


def _storyboard_artifacts(
    directory: Path, payload: Mapping[str, Any]
) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    for shot in payload["shots"]:
        shot_id = str(shot["shot_id"])
        board_artifacts: list[tuple[str, str]] = []
        if isinstance(shot.get("boards"), list):
            for board in shot["boards"]:
                board_artifacts.extend(
                    (
                        ("raw_board", str(board["raw_board"])),
                        ("review_board", str(board["review_board"])),
                        ("imagine_prompt", str(board["imagine_prompt"])),
                    )
                )
        else:
            board_artifacts.append(("review_board", str(shot["review_board"])))
        for role, value in (
            *board_artifacts,
            *[("generation_image", path) for path in shot["generation_images"]],
        ):
            path = _inside(directory, str(value))
            artifacts.append(
                {
                    "shot_id": shot_id,
                    "role": role,
                    "path": str(path.relative_to(directory.resolve())),
                    "sha256": sha256_file(path),
                }
            )
    return artifacts


def storyboard_approval_snapshot(
    directory: Path, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Freeze the exact manifest and storyboard bytes the user approved."""

    validate_storyboard_manifest(directory, payload)
    artifacts = _storyboard_artifacts(directory, payload)
    manifest_sha256 = sha256_file(directory / "storyboard-manifest.json")
    review_bundle = [
        {
            "role": "storyboard_manifest",
            "path": "storyboard-manifest.json",
            "sha256": manifest_sha256,
        },
        *artifacts,
    ]
    return {
        "approval_scope": "full_storyboards_and_h3_prompts",
        "review_bundle_sha256": _review_bundle_sha256(review_bundle),
        "manifest_sha256": manifest_sha256,
        "artifacts": artifacts,
    }


def validate_storyboard_approval(
    task: Mapping[str, Any], directory: Path, payload: Mapping[str, Any]
) -> None:
    """Prove the current storyboards are byte-for-byte what the user approved.

    Every AutoDL task must carry the immutable snapshot.
    """

    approval = task.get("storyboard_approval")
    if not isinstance(approval, Mapping) or approval.get("status") != "approved":
        raise BrollTaskError("Codex Imagine storyboards require user approval before pricing")
    if (
        task.get("shot_plan_approval", {}).get("status") != "not_required"
        and approval.get("approval_source") != "explicit_user_instruction"
    ):
        raise BrollTaskError(
            "storyboard approval is not backed by an explicit user instruction"
        )
    expected_manifest = approval.get("manifest_sha256")
    expected_artifacts = approval.get("artifacts")
    if not isinstance(expected_manifest, str) or not isinstance(expected_artifacts, list):
        raise BrollTaskError("storyboard approval lacks its immutable hash snapshot; approve again")
    current = storyboard_approval_snapshot(directory, payload)
    if any(
        approval.get(field) != current[field]
        for field in (
            "approval_scope",
            "review_bundle_sha256",
            "manifest_sha256",
            "artifacts",
        )
    ):
        raise BrollTaskError("storyboards changed after approval; user approval is required again")


def _approved_reference_assets(
    directory: Path, manifest: Mapping[str, Any], shot_ids: set[str]
) -> dict[str, list[dict[str, str]]]:
    """Validate explicitly user-approved non-storyboard media without conflating it with boards."""

    raw_assets = manifest.get("approved_reference_assets", [])
    if raw_assets is None:
        raw_assets = []
    if not isinstance(raw_assets, list):
        raise BrollTaskError("approved_reference_assets must be an array when present")
    scoped: dict[str, list[dict[str, str]]] = {shot_id: [] for shot_id in shot_ids}
    for item in raw_assets:
        if not isinstance(item, Mapping):
            raise BrollTaskError("each approved reference asset must be an object")
        required = {
            "path",
            "sha256",
            "source",
            "rights_note",
            "approved_by",
            "allowed_shot_ids",
            "allowed_profiles",
            "role",
        }
        missing = sorted(required - set(item))
        if missing:
            raise BrollTaskError("approved reference asset is missing fields: " + ", ".join(missing))
        path = _inside(directory, str(item["path"]))
        digest = str(item["sha256"]).lower()
        source = str(item["source"]).strip()
        rights_note = str(item["rights_note"]).strip()
        role = str(item["role"])
        allowed_shot_ids = item["allowed_shot_ids"]
        allowed_profiles = item["allowed_profiles"]
        if not path.is_file() or path.stat().st_size == 0:
            raise BrollTaskError(f"approved reference asset is missing/empty: {path}")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise BrollTaskError("approved reference asset sha256 must be a lowercase SHA-256")
        if sha256_file(path) != digest:
            raise BrollTaskError(f"approved reference asset sha256 differs: {path}")
        if not source or not rights_note or item["approved_by"] != "user":
            raise BrollTaskError("approved reference asset requires source, rights_note, and approved_by=user")
        if role not in _ADDITIONAL_REFERENCE_ROLES:
            raise BrollTaskError("approved reference assets may only be reference_video or reference_audio")
        if (
            not isinstance(allowed_shot_ids, list)
            or not allowed_shot_ids
            or not all(isinstance(value, str) and value in shot_ids for value in allowed_shot_ids)
        ):
            raise BrollTaskError("approved reference asset has invalid allowed_shot_ids")
        if (
            not isinstance(allowed_profiles, list)
            or not allowed_profiles
            or not all(isinstance(value, str) and value in _PROVIDER_PROFILES for value in allowed_profiles)
        ):
            raise BrollTaskError("approved reference asset has invalid allowed_profiles")
        approved = {
            "path": str(path),
            "sha256": digest,
            "source": source,
            "rights_note": rights_note,
            "role": role,
            "allowed_profiles": ",".join(allowed_profiles),
        }
        for shot_id in allowed_shot_ids:
            scoped[shot_id].append(approved)
    return scoped


def validate_approved_request_media(
    directory: Path, manifest: Mapping[str, Any], shot_id: str, request: Any
) -> None:
    """Require ordered approved boards followed only by exact approved auxiliary media."""

    shots = manifest.get("shots", [])
    shot = next((item for item in shots if isinstance(item, Mapping) and item.get("shot_id") == shot_id), None)
    if shot is None:
        raise BrollTaskError(f"request refers to unknown approved shot: {shot_id}")
    approved_images = [str(_inside(directory, str(path))) for path in shot["generation_images"]]
    approved_assets = _approved_reference_assets(
        directory, manifest, {str(item["shot_id"]) for item in shots if isinstance(item, Mapping)}
    )[shot_id]
    if len(request.media) != len(approved_images) + len(approved_assets):
        raise BrollTaskError(f"{shot_id} media count differs from approved boards plus reference assets")
    for actual, expected_path in zip(request.media[: len(approved_images)], approved_images):
        actual_path = str(Path(actual.source).expanduser().resolve())
        if actual_path != expected_path or actual.role not in _GENERATION_IMAGE_ROLES:
            raise BrollTaskError(f"{shot_id} does not use ordered user-approved Imagine boards")
        if sha256_file(Path(actual_path)) != sha256_file(Path(expected_path)):
            raise BrollTaskError(f"{shot_id} approved storyboard bytes differ")
    for actual, expected in zip(request.media[len(approved_images) :], approved_assets):
        actual_path = str(Path(actual.source).expanduser().resolve())
        profiles = set(expected["allowed_profiles"].split(","))
        if (
            actual_path != expected["path"]
            or actual.role != expected["role"]
            or request.provider_profile not in profiles
            or sha256_file(Path(actual_path)) != expected["sha256"]
            or actual.source_origin != expected["source"]
            or actual.rights_note != expected["rights_note"]
        ):
            raise BrollTaskError(f"{shot_id} auxiliary reference differs from explicit user approval")


def current_attempts(directory: Path) -> dict[str, Path]:
    attempts: dict[str, Path] = {}
    root = directory / "h3-requests"
    if not root.is_dir():
        return attempts
    for request_path in sorted(root.glob("*/attempt-*/request.json")):
        shot_id = request_path.parent.parent.name
        attempts[shot_id] = request_path
    return attempts


def _validate_requests(
    task: Mapping[str, Any], directory: Path, manifest: Mapping[str, Any]
) -> Any:
    if task.get("spec", {}).get("production_contract") == GOLD_PRODUCTION_CONTRACT:
        from .gold_contract import validate_gold_request_set

        return validate_gold_request_set(task, directory, manifest)
    attempts = current_attempts(directory)
    approved = {
        str(item["shot_id"]): [str(_inside(directory, str(path))) for path in item["generation_images"]]
        for item in manifest["shots"]
    }
    if set(attempts) != set(approved):
        missing = sorted(set(approved) - set(attempts))
        extra = sorted(set(attempts) - set(approved))
        raise BrollTaskError(f"H3 requests do not match approved shots; missing={missing}, extra={extra}")
    for shot_id, path in attempts.items():
        request = load_request(path, expected_provider=task_provider(task))
        if request.ratio != task["spec"]["ratio"]:
            raise BrollTaskError(f"{shot_id} ratio differs from task authority")
        if request.resolution != task["spec"]["resolution"]:
            raise BrollTaskError(f"{shot_id} resolution differs from task authority")
        validate_approved_request_media(directory, manifest, shot_id, request)
    return attempts


def next_action(store: BrollTaskStore, task_id: str) -> dict[str, Any]:
    task = store.load(task_id)
    directory = store.directory(task_id)
    provider = task_provider(task)
    runtime = "h3-video-runtime"
    provider_label = "AutoDL"
    copied = directory / str(task["source"]["copied_srt"])
    if not copied.is_file() or sha256_file(copied) != task["source"]["sha256"]:
        return _decision("blocked", "source_srt_changed", "恢复原始 SRT；不得从摘要或改写稿继续")

    visual_lock_path = directory / "visual-lock.json"
    visual_review_path = directory / "visual-lock.md"
    if not visual_lock_path.is_file() or not visual_review_path.is_file():
        return _decision(
            "needs_visual_lock",
            "srt-broll-producer",
            "先取得内容/场景风格参考与口播衔接参考，冻结视觉权威后才能设计场景和摄影",
        )
    try:
        validate_visual_lock(
            directory,
            task,
            json.loads(visual_lock_path.read_text(encoding="utf-8")),
        )
    except (OSError, json.JSONDecodeError, BrollTaskError) as exc:
        return _decision("needs_visual_lock", "srt-broll-producer", str(exc))

    plan_path = directory / "shot-plan.json"
    review_path = directory / "shot-plan.md"
    if not plan_path.is_file() or not review_path.is_file():
        return _decision(
            "needs_shot_plan",
            "srt-broll-producer",
            "完整读取 SRT，先理解全篇，再只选择真正需要 B-roll 的区间",
        )
    try:
        plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
        validate_shot_plan(task, plan_payload)
    except (OSError, json.JSONDecodeError, BrollTaskError) as exc:
        return _decision("needs_shot_plan", "srt-broll-producer", str(exc))

    if _shot_plan_approval_required(task, plan_payload):
        if task.get("shot_plan_approval", {}).get("status") != "approved":
            return _decision(
                "awaiting_shot_plan_approval",
                "user",
                "等待用户明确批准 visual-lock.json/md 与 shot-plan.json/md；批准前禁止生成或验证故事板样板",
            )
        try:
            validate_shot_plan_approval(task, directory, plan_payload)
        except BrollTaskError as exc:
            return _decision("awaiting_shot_plan_reapproval", "user", str(exc))

    board_plan_path = directory / "storyboard-board-plan.json"
    if not board_plan_path.is_file():
        return _decision(
            "needs_storyboard_board_plan",
            "broll-storyboard-producer",
            "先按语义容量判断每个单元需要 1-4 张故事板，再生成每张严格四格的画面",
        )
    try:
        validate_storyboard_board_plan(
            directory,
            task,
            json.loads(board_plan_path.read_text(encoding="utf-8")),
            plan_payload,
        )
    except (OSError, json.JSONDecodeError, BrollTaskError) as exc:
        return _decision(
            "needs_storyboard_board_plan", "broll-storyboard-producer", str(exc)
        )
    if task.get("spec", {}).get("production_contract") == GOLD_PRODUCTION_CONTRACT:
        sample_path = directory / "storyboard-sample.json"
        if not sample_path.is_file():
            return _decision(
                "needs_storyboard_sample",
                "broll-storyboard-producer",
                "从完整镜头计划中选 1-2 个代表镜头生成样板；确认前禁止扩展全量故事板",
            )
        try:
            sample = json.loads(sample_path.read_text(encoding="utf-8"))
            validate_storyboard_sample(directory, sample)
        except (OSError, json.JSONDecodeError, BrollTaskError) as exc:
            return _decision("needs_storyboard_sample", "broll-storyboard-producer", str(exc))
        if task.get("storyboard_sample_approval", {}).get("status") != "approved":
            return _decision(
                "awaiting_storyboard_sample_approval",
                "user",
                "等待用户确认 1-2 个代表性故事板样板；确认前禁止全量生成",
            )
        try:
            _validated_approved_storyboard_sample(task, directory, plan_payload)
        except (OSError, json.JSONDecodeError, BrollTaskError) as exc:
            return _decision("awaiting_storyboard_sample_reapproval", "user", str(exc))
    manifest_path = directory / "storyboard-manifest.json"
    if not manifest_path.is_file():
        return _decision(
            "needs_storyboards",
            "broll-storyboard-producer",
            "用 Codex Imagine 生成固定四格 review boards，并从全部 Panel 选择 3-5 张干净 H3 anchors",
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            task.get("spec", {}).get("workflow_contract")
            == THREE_STAGE_WORKFLOW_CONTRACT
            and any(
                not str(item.get("h3_request_prompt", "")).strip()
                for item in manifest.get("shots", [])
                if isinstance(item, Mapping)
            )
        ):
            return _decision(
                "needs_h3_prompts",
                "broll-storyboard-producer",
                f"先执行 broll-video prepare-h3-prompts {task_id}，把 H3 生成脚本写入全量 manifest，再交给用户确认分镜",
            )
        validate_storyboard_manifest(directory, manifest)
    except (OSError, json.JSONDecodeError, BrollTaskError) as exc:
        if "frozen H3 generation script" in str(exc):
            return _decision("needs_h3_prompts", "broll-storyboard-producer", str(exc))
        return _decision("needs_storyboards", "broll-storyboard-producer", str(exc))
    if task["storyboard_approval"]["status"] != "approved":
        return _decision(
            "awaiting_storyboard_approval",
            "user",
            "等待用户确认故事板；确认前禁止编译或提交付费视频任务",
        )
    try:
        validate_storyboard_approval(task, directory, manifest)
    except BrollTaskError as exc:
        return _decision("awaiting_storyboard_reapproval", "user", str(exc))
    try:
        attempts = _validate_requests(task, directory, manifest)
    except BrollTaskError as exc:
        if task.get("spec", {}).get("production_contract") == GOLD_PRODUCTION_CONTRACT:
            return _decision(
                "needs_h3_requests",
                "h3-video-runtime",
                f"{exc}；只能执行 broll-video compile-h3 {task_id}",
            )
        return _decision("needs_h3_requests", runtime, str(exc))

    plan = directory / "generation-plan.json"
    if not plan.is_file():
        request_count = (
            sum(len(paths) for paths in attempts.values())
            if task.get("spec", {}).get("production_contract") == GOLD_PRODUCTION_CONTRACT
            else len(attempts)
        )
        return _decision(
            "ready_for_pricing",
            runtime,
            f"{request_count} 个黄金契约请求可通过 {provider_label} 进行关机状态 dry-run 与整批估价",
        )
    delivery = directory / "delivery-manifest.json"
    if delivery.is_file():
        if task["delivery"]["human_review"] == "accepted":
            return _decision("accepted", None, "B-roll 已下载、交付并经用户人工审片接受")
        return _decision(
            "human_review_pending",
            "user",
            "独立 B-roll 已下载并完成快速收货，等待用户判断画面、节奏和审美",
        )
    return _decision(
        "ready_for_generation" if task["execution"]["mode"] == "authorized" else "estimate_only",
        runtime,
        f"计划已锁定；授权模式可通过 {provider_label} 执行，估价模式不得提交",
    )


def _decision(state: str, skill: str | None, reason: str) -> dict[str, Any]:
    return {"state": state, "next_skill": skill, "reason": reason}


__all__ = [
    "current_attempts",
    "next_action",
    "validate_shot_plan",
    "shot_plan_approval_snapshot",
    "validate_shot_plan_approval",
    "validate_approved_generate_set",
    "validate_storyboard_manifest",
    "validate_storyboard_sample",
    "storyboard_sample_approval_snapshot",
    "storyboard_approval_snapshot",
    "validate_storyboard_approval",
    "validate_approved_request_media",
]
