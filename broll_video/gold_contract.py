"""Deterministic compiler for the production method proven by the first live run."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

from .h3 import H3Request, MediaAsset
from .h3.models import H3InputError
from .h3.prompt_gate import (
    PROMPT_MAX_CHARACTERS,
    SFX_ONLY_GUARD,
    VISUAL_GUARD,
    validate_h3_motion_prompt,
)
from .requests import load_request, request_to_dict
from .task import (
    GOLD_PRODUCTION_CONTRACT,
    THREE_STAGE_WORKFLOW_CONTRACT,
    BrollTaskError,
    BrollTaskStore,
)


DRAW_OFFSETS = (0, 1_000_003)
_VOICE_OR_MUSIC = re.compile(
    r"(?:music|soundtrack|score|melody|sing|humming|voice|dialogue|narration|"
    r"音乐|配乐|歌曲|歌声|人声|对话|口播|旁白|说话|台词)",
    re.IGNORECASE,
)
def compile_gold_requests(store: BrollTaskStore, task_id: str) -> dict[str, Any]:
    """Create the exact task-authorized immutable requests per approved shot."""

    task, directory, plan, manifest = _load_gold_authority(store, task_id)
    expected = _expected_request_payloads(task, directory, plan, manifest)
    existing = {
        path.relative_to(directory).as_posix(): path
        for path in sorted(directory.glob("h3-requests/*/attempt-*/request.json"))
    }
    extras = set(existing) - set(expected)
    if extras:
        raise BrollTaskError(
            "gold request directory contains unexpected attempts; do not improvise or clone the task"
        )
    for relative, path in existing.items():
        if relative not in expected:
            continue
        try:
            actual = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BrollTaskError(f"gold H3 request is unreadable: {relative}") from exc
        if actual != expected[relative]:
            raise BrollTaskError(
                f"gold H3 request differs from the deterministic compiler: {relative}"
            )
    for relative, payload in expected.items():
        if relative not in existing:
            _atomic_json(directory / relative, payload)
    validate_gold_request_set(task, directory, manifest, expected=expected)
    draws_per_shot = int(task["spec"]["draws_per_shot"])
    return {
        "task_id": task_id,
        "production_contract": GOLD_PRODUCTION_CONTRACT,
        "shots": len(manifest["shots"]),
        "requests": len(expected),
        "provider_profile": "precision_keyframes",
        "draws_per_shot": draws_per_shot,
        "audio_policy": task["spec"]["audio_policy"],
        "execution_order": "pipelined_single_generate_single_download",
        "download_queue_capacity": 4,
    }


def prepare_h3_prompts(store: BrollTaskStore, task_id: str) -> dict[str, Any]:
    """Stage 2: freeze H3 generation scripts before storyboard approval."""

    from .producer import validate_shot_plan, validate_storyboard_manifest

    task = store.load(task_id)
    directory = store.directory(task_id)
    if task.get("storyboard_approval", {}).get("status") == "approved":
        raise BrollTaskError(
            "approved storyboard manifest is immutable; revoke and rebuild the stage-2 bundle"
        )
    try:
        plan = json.loads((directory / "shot-plan.json").read_text(encoding="utf-8"))
        manifest = json.loads(
            (directory / "storyboard-manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise BrollTaskError("H3 prompt preparation requires shot plan and storyboard manifest") from exc
    validate_shot_plan(task, plan)
    validate_storyboard_manifest(directory, manifest, require_h3_prompts=False)
    shot_by_id = {str(shot["shot_id"]): shot for shot in plan["shots"]}
    guard = str(manifest.get("h3_visual_guard", "")).strip()
    for manifest_shot in manifest["shots"]:
        shot_id = str(manifest_shot["shot_id"])
        manifest_shot["h3_request_prompt"] = _compile_prompt(
            task,
            shot_by_id[shot_id],
            manifest_shot,
            guard,
            anchor_count=len(manifest_shot["generation_images"]),
        )
    _atomic_json(directory / "storyboard-manifest.json", manifest)
    validate_storyboard_manifest(directory, manifest)
    return {
        "task_id": task_id,
        "stage": 2,
        "prompts": len(manifest["shots"]),
        "manifest_sha256": _sha256_file(directory / "storyboard-manifest.json"),
        "next": (
            f"broll-video approve-storyboards {task_id} "
            "--approval-source explicit_user_instruction"
        ),
    }


def validate_gold_request_set(
    task: Mapping[str, Any],
    directory: Path,
    manifest: Mapping[str, Any],
    *,
    expected: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, list[Path]]:
    """Reject any hand-authored deviation before pricing or paid submission."""

    if task.get("spec", {}).get("production_contract") != GOLD_PRODUCTION_CONTRACT:
        raise BrollTaskError("task is not bound to agent-know-gold-v1")
    if expected is None:
        try:
            plan = json.loads((directory / "shot-plan.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BrollTaskError("gold request validation requires a valid shot plan") from exc
        expected = _expected_request_payloads(task, directory, plan, manifest)
    actual_paths = {
        path.relative_to(directory).as_posix(): path
        for path in sorted(directory.glob("h3-requests/*/attempt-*/request.json"))
    }
    missing = sorted(set(expected) - set(actual_paths))
    extras = set(actual_paths) - set(expected)
    if missing or extras:
        extra = sorted(extras)
        raise BrollTaskError(
            f"gold H3 request set is not exact; missing={missing}, extra={extra}"
        )
    by_shot: dict[str, list[Path]] = {
        str(item["shot_id"]): [] for item in manifest["shots"]
    }
    for relative, expected_payload in expected.items():
        path = actual_paths[relative]
        try:
            actual = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BrollTaskError(f"gold H3 request is unreadable: {relative}") from exc
        if actual != expected_payload:
            raise BrollTaskError(f"gold H3 request was edited after compilation: {relative}")
        request = load_request(path, expected_provider="autodl")
        if (
            request.production_contract != GOLD_PRODUCTION_CONTRACT
            or request.provider_profile != "precision_keyframes"
            or request.audio_policy != task.get("spec", {}).get("audio_policy")
            or not 3 <= len(request.media) <= 5
            or len(request.prompt) > PROMPT_MAX_CHARACTERS
        ):
            raise BrollTaskError(f"gold H3 request violates the locked production contract: {relative}")
        by_shot[path.parent.parent.name].append(path)
    draws_per_shot = int(task.get("spec", {}).get("draws_per_shot", 2))
    if any(len(paths) != draws_per_shot for paths in by_shot.values()):
        raise BrollTaskError(
            "gold production requests must exactly match task-authorized draws per shot"
        )
    return by_shot


def _load_gold_authority(
    store: BrollTaskStore, task_id: str
) -> tuple[dict[str, Any], Path, dict[str, Any], dict[str, Any]]:
    from .producer import (
        validate_shot_plan,
        validate_storyboard_approval,
        validate_storyboard_manifest,
    )

    task = store.load(task_id)
    directory = store.directory(task_id)
    if task.get("spec", {}).get("production_contract") != GOLD_PRODUCTION_CONTRACT:
        raise BrollTaskError("compile-h3 is reserved for agent-know-gold-v1 tasks")
    if task.get("storyboard_approval", {}).get("status") != "approved":
        raise BrollTaskError("full storyboards require user approval before H3 compilation")
    try:
        plan = json.loads((directory / "shot-plan.json").read_text(encoding="utf-8"))
        manifest = json.loads(
            (directory / "storyboard-manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise BrollTaskError("gold compilation requires a valid shot plan and manifest") from exc
    validate_shot_plan(task, plan)
    validate_storyboard_manifest(directory, manifest)
    validate_storyboard_approval(task, directory, manifest)
    return task, directory, plan, manifest


def _expected_request_payloads(
    task: Mapping[str, Any],
    directory: Path,
    plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    if manifest.get("approved_reference_assets"):
        raise BrollTaskError("gold production accepts only the approved storyboard anchors")
    shot_by_id = {str(shot["shot_id"]): shot for shot in plan["shots"]}
    guard = str(manifest.get("h3_visual_guard", "")).strip()
    draws_per_shot = int(task.get("spec", {}).get("draws_per_shot", 2))
    attempt_names = tuple(
        f"attempt-{attempt_number:03d}"
        for attempt_number in range(1, draws_per_shot + 1)
    )
    audio_policy = str(task.get("spec", {}).get("audio_policy", "sfx_only"))
    expected: dict[str, dict[str, Any]] = {}
    for manifest_shot in manifest["shots"]:
        shot_id = str(manifest_shot["shot_id"])
        shot = shot_by_id[shot_id]
        anchor_times = manifest_shot.get("generation_anchor_times_seconds")
        prompt = str(manifest_shot.get("h3_request_prompt", "")).strip()
        if not prompt:
            raise BrollTaskError(
                f"{shot_id} has no stage-2 approved H3 prompt in storyboard-manifest.json"
            )
        expected_prompt = _compile_prompt(
            task,
            shot,
            manifest_shot,
            guard,
            anchor_count=len(manifest_shot["generation_images"]),
        )
        if prompt != expected_prompt:
            raise BrollTaskError(
                f"{shot_id} H3 generation script is not the deterministic rendering of the approved storyboard panels"
            )
        assets = tuple(
            MediaAsset(
                source=str((directory / str(source)).resolve()),
                role="reference_image",
                semantic_role="keyframe",
                must_preserve=(
                    "approved subject identity",
                    "approved physical scene content",
                    "approved palette and lighting direction",
                    "approved in-scene text when present",
                ),
                may_change=(
                    "only the scripted physical action, camera movement and environmental motion",
                ),
                used_by=(shot_id,),
                prompt_label=f"{shot_id} approved keyframe {index}",
                frame_index=(
                    round(float(anchor_times[index - 1]) * 24)
                    if isinstance(anchor_times, list)
                    else None
                ),
            )
            for index, source in enumerate(manifest_shot["generation_images"], start=1)
        )
        seed_base = int.from_bytes(hashlib.sha256(shot_id.encode("utf-8")).digest()[:7], "big")
        for attempt_name, seed_offset in zip(attempt_names, DRAW_OFFSETS):
            request = H3Request(
                prompt=prompt,
                duration=int(shot["generation_duration"]),
                ratio=str(task["spec"]["ratio"]),
                resolution="4K",
                media=assets,
                provider_profile="precision_keyframes",
                seed=seed_base + seed_offset,
                audio_policy=audio_policy,
                production_contract=GOLD_PRODUCTION_CONTRACT,
            )
            relative = f"h3-requests/{shot_id}/{attempt_name}/request.json"
            expected[relative] = request_to_dict(request, provider="autodl")
    return expected


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compile_prompt(
    task: Mapping[str, Any],
    shot: Mapping[str, Any],
    storyboard_shot: Mapping[str, Any],
    visual_guard: str,
    *,
    anchor_count: int,
) -> str:
    duration = int(shot["generation_duration"])
    boards = storyboard_shot.get("boards")
    if not isinstance(boards, list) or not boards:
        raise BrollTaskError(
            f"{shot['shot_id']} H3 script compilation requires approved four-panel boards"
        )
    beats = [
        panel
        for board in boards
        if isinstance(board, Mapping)
        for panel in board.get("panels", [])
        if isinstance(panel, Mapping)
    ]
    camera_fields = ("shot_number", "framing", "camera", "transition_in")
    has_camera_plan = any(
        any(str(beat.get(field, "")).strip() for field in camera_fields)
        for beat in beats
    )
    if (
        task.get("spec", {}).get("workflow_contract")
        == THREE_STAGE_WORKFLOW_CONTRACT
        and not has_camera_plan
    ):
        raise BrollTaskError(
            f"{shot['shot_id']} three-stage workflow requires a complete semantic camera plan"
        )
    if has_camera_plan and any(
        not all(str(beat.get(field, "")).strip() for field in camera_fields)
        for beat in beats
    ):
        raise BrollTaskError(
            f"{shot['shot_id']} camera planning must fill shot_number, framing, camera and transition_in for every beat"
        )

    beat_lines: list[str] = []
    previous_shot = 0
    for beat in beats:
        relative_time = str(beat.get("time", "")).strip()
        visual_content = str(
            beat.get("visual_content", beat.get("action_result", ""))
        ).strip()
        # Storyboard prose may call a visible document "口播证据" and then say
        # that people do not appear.  The upload gate correctly rejects positive
        # voice requests, but that wording creates a false positive around
        # "口播…出现".  Normalize only the non-visual editorial noun here; the
        # approved visible subject, action, timing and text remain unchanged.
        visual_content = visual_content.replace("口播证据", "岗位证据")
        if not relative_time or not visual_content:
            raise BrollTaskError(
                f"{shot['shot_id']} each H3 beat requires a relative time and visible content"
            )
        required_text = beat.get("required_text", [])
        if required_text:
            visual_content += "；画内必要文字：" + "、".join(
                str(value) for value in required_text
            )
        if not has_camera_plan:
            beat_lines.append(f"{relative_time}：{visual_content}")
            continue

        try:
            shot_number = int(str(beat["shot_number"]))
        except ValueError as exc:
            raise BrollTaskError(
                f"{shot['shot_id']} shot_number must be an integer"
            ) from exc
        framing = str(beat["framing"]).strip()
        camera = str(beat["camera"]).strip()
        transition_in = str(beat["transition_in"]).strip()
        if previous_shot == 0:
            if shot_number != 1 or transition_in != "start":
                raise BrollTaskError(
                    f"{shot['shot_id']} camera plan must begin with Shot 1 and transition_in=start"
                )
            beat_lines.append(
                f"[Shot 1] {relative_time}：{framing}；{camera}；{visual_content}"
            )
        elif shot_number == previous_shot:
            if transition_in != "continue":
                raise BrollTaskError(
                    f"{shot['shot_id']} repeated shot_number requires transition_in=continue"
                )
            beat_lines.append(
                f"{relative_time}：Shot {shot_number} 内继续；{camera}；{visual_content}"
            )
        elif shot_number == previous_shot + 1:
            if transition_in in {"start", "continue"}:
                raise BrollTaskError(
                    f"{shot['shot_id']} a new shot requires a cut transition"
                )
            cut = {
                "match_cut": "a match cut reveals",
                "occlusion_cut": "an occlusion cut reveals",
            }.get(transition_in, "the camera cuts to")
            beat_lines.append(
                f"[Shot {shot_number}] At {_relative_clock(relative_time)}, {cut} "
                f"{framing}；{camera}；{visual_content}"
            )
        else:
            raise BrollTaskError(
                f"{shot['shot_id']} shot_number must stay the same or advance by one"
            )
        previous_shot = shot_number
    transitions = "; ".join(
        f"Shot {int(beat['shot_number'])} 使用 {str(beat['transition_in']).strip()}"
        for beat in beats
        if str(beat.get("transition_in", "")).strip()
        not in {"start", "continue"}
    )
    if task.get("spec", {}).get("audio_policy") == "silent":
        audio = "全程静音，不生成音效、人声、旁白、对话或音乐。"
    else:
        sfx = _physical_sfx_only(str(shot["sound_intent"]))
        audio = f"同步音效：{sfx}。{SFX_ONLY_GUARD}"
    prompt = (
        f"图1至图{anchor_count}是这个{duration}秒、{task['spec']['ratio']}视频唯一的画面与风格标准，"
        "按顺序对应以下相对时间段。"
        f"{VISUAL_GUARD}\n"
        + ("以下 [Shot N] 都在同一条视频内按已确认的时间与镜头节拍切换，不拆成多条素材。\n" if has_camera_plan else "")
        + "时间编排：\n"
        + "\n".join(beat_lines)
        + f"\n运镜与图间转场：{transitions or '保持同一空间或视觉系统内的信息连续推进'}。\n"
        + f"固定项：{visual_guard}\n"
        + audio
    )
    try:
        validate_h3_motion_prompt(
            prompt,
            anchor_count=anchor_count,
            audio_policy=str(task.get("spec", {}).get("audio_policy", "")),
            duration=duration,
            ratio=str(task.get("spec", {}).get("ratio", "")),
            label=f"{shot['shot_id']} compiled H3 prompt",
        )
    except H3InputError as exc:
        raise BrollTaskError(str(exc)) from exc
    return prompt


def _relative_clock(value: str) -> str:
    match = re.match(r"\s*(\d+(?:\.\d+)?)", value)
    if match is None:
        raise BrollTaskError(f"relative beat time has no numeric start: {value}")
    milliseconds = round(float(match.group(1)) * 1000)
    minutes, remainder = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def _physical_sfx_only(value: str) -> str:
    clauses = [part.strip(" ,、") for part in re.split(r"[;；\n]+", value) if part.strip()]
    physical = [part for part in clauses if not _VOICE_OR_MUSIC.search(part)]
    return "; ".join(physical) or "仅保留画面内可见动作和自然环境产生的声音"


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


__all__ = ["compile_gold_requests", "prepare_h3_prompts", "validate_gold_request_set"]
