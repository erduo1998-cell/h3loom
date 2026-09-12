"""Durable, minimal authority for one SRT-to-B-roll production task."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Mapping
from uuid import uuid4


RATIOS = {"21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}
RESOLUTIONS = {"768P", "4K"}
EXECUTION_MODES = {"estimate_only", "authorized"}
MAX_BUDGET_CNY = 50.0
DEFAULT_PROVIDER = "autodl"
GOLD_PRODUCTION_CONTRACT = "agent-know-gold-v1"
PRODUCTION_CONTRACTS = {GOLD_PRODUCTION_CONTRACT}
THREE_STAGE_WORKFLOW_CONTRACT = "three-stage-four-panel-v1"
APPROVAL_SOURCE_EXPLICIT_USER = "explicit_user_instruction"
INHERITANCE_MODES = {
    "resume",
    "regenerate",
    "additive",
    "replace",
    "fresh_redesign",
}
ASSET_DISPOSITIONS = {"retain", "replace", "additive", "archive-only"}
ASSET_VARIANT_ROLES = {"primary", "backup", "superseded", "archive-only"}
_FOUR_K_DIMENSIONS = {
    "21:9": (3840, 1648),
    "16:9": (3840, 2160),
    "4:3": (4096, 3072),
    "1:1": (3840, 3840),
    "3:4": (3072, 4096),
    "9:16": (2160, 3840),
}
_PROVIDER_BACKENDS = {
    "autodl": "autodl-comfy-h3",
}


class BrollTaskError(ValueError):
    """Raised when task authority or a workflow gate is invalid."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", value.strip()).strip("-")
    return cleaned[:48] or "broll"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def task_provider(payload: Mapping[str, Any]) -> str:
    """Return the task's single supported AutoDL provider."""

    spec = payload.get("spec")
    if not isinstance(spec, Mapping):
        raise BrollTaskError("task authority has no readable video spec")
    provider = spec.get("provider")
    backend = spec.get("backend")
    if provider not in _PROVIDER_BACKENDS:
        raise BrollTaskError("video provider is unsupported")
    if backend != _PROVIDER_BACKENDS[provider]:
        raise BrollTaskError("video provider and backend differ")
    return str(provider)


class BrollTaskStore:
    def __init__(self, root: Path | str = "work/tasks") -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, task_id: str) -> Path:
        if Path(task_id).name != task_id or task_id in {".", ".."}:
            raise BrollTaskError("invalid task id")
        return self.root / task_id

    def create(
        self,
        *,
        name: str,
        source_srt: Path | str,
        ratio: str,
        resolution: str = "4K",
        budget_cny: float = 20.0,
        execution_mode: str = "estimate_only",
        annotations: list[str] | None = None,
        inputs: list[str] | None = None,
        forbidden: list[str] | None = None,
        production_contract: str | None = GOLD_PRODUCTION_CONTRACT,
        deterministic_gates: bool = True,
    ) -> dict[str, Any]:
        source = Path(source_srt).expanduser().resolve()
        if not source.is_file() or source.stat().st_size == 0:
            raise BrollTaskError(f"source SRT is missing or empty: {source}")
        if source.suffix.lower() != ".srt":
            raise BrollTaskError("source file must be .srt")
        normalized_ratio = ratio.strip().replace("：", ":").replace(" ", "")
        if normalized_ratio not in RATIOS:
            raise BrollTaskError(f"unsupported ratio: {normalized_ratio}")
        normalized_resolution = resolution.strip().upper()
        if normalized_resolution not in RESOLUTIONS:
            raise BrollTaskError("resolution must be base H3 (768P label) or cloud RTX 4K")
        if production_contract is not None and production_contract not in PRODUCTION_CONTRACTS:
            raise BrollTaskError("unsupported production contract")
        if production_contract == GOLD_PRODUCTION_CONTRACT and normalized_resolution != "4K":
            raise BrollTaskError("agent-know-gold-v1 locks production delivery to 4K")
        if execution_mode not in EXECUTION_MODES:
            raise BrollTaskError("execution mode must be estimate_only or authorized")
        try:
            budget = round(float(budget_cny), 2)
        except (TypeError, ValueError) as exc:
            raise BrollTaskError("budget must be a CNY number") from exc
        if not 0 < budget <= MAX_BUDGET_CNY:
            raise BrollTaskError("task budget must be within 0-50 CNY")
        input_sources = [Path(value).expanduser().resolve() for value in (inputs or [])]
        for original in input_sources:
            if not original.is_file() or original.stat().st_size == 0:
                raise BrollTaskError(f"input asset is missing or empty: {original}")
        task_id = f"{datetime.now().strftime('%Y%m%d')}-{_slug(name)}-{uuid4().hex[:8]}"
        directory = self.directory(task_id)
        directory.mkdir(parents=True)
        for relative in (
            "inputs",
            "storyboards/raw",
            "storyboards/review",
            "storyboards/generation",
            "storyboards/prompts",
            "h3-requests",
            f"provider/{DEFAULT_PROVIDER}",
        ):
            (directory / relative).mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, directory / "source.srt")
        frozen_inputs: list[dict[str, str]] = []
        for index, original in enumerate(input_sources, start=1):
            copied = directory / "inputs" / f"{index:02d}-{original.name}"
            shutil.copy2(original, copied)
            frozen_inputs.append(
                {
                    "original": str(original),
                    "copied": str(copied.relative_to(directory)),
                    "sha256": sha256_file(copied),
                }
            )
        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "task_id": task_id,
            "task_name": name.strip(),
            "created_at": now(),
            "updated_at": now(),
            "intent": "从完整口播 SRT 生成按时间码对齐、供人工审片的独立 B-roll 素材",
            "source": {
                "original_srt": str(source),
                "copied_srt": "source.srt",
                "sha256": sha256_file(directory / "source.srt"),
                "annotations": list(annotations or []),
                "inputs": frozen_inputs,
                "forbidden": list(forbidden or []),
            },
            "spec": {
                "ratio": normalized_ratio,
                "resolution": normalized_resolution,
                "provider": DEFAULT_PROVIDER,
                "backend": _PROVIDER_BACKENDS[DEFAULT_PROVIDER],
                "storyboard_backend": "codex-imagine",
                "audio": (
                    "STRICT SFX ONLY: synchronized visible action and environmental sounds; "
                    "absolutely no music, dialogue, narration, voices, or off-screen sound"
                    if production_contract == GOLD_PRODUCTION_CONTRACT
                    else "synchronized diegetic SFX only; no music, dialogue, narration, or voices"
                ),
                **(
                    {
                        "production_contract": GOLD_PRODUCTION_CONTRACT,
                        "workflow_contract": THREE_STAGE_WORKFLOW_CONTRACT,
                        "provider_profile": "precision_keyframes",
                        "audio_policy": "sfx_only",
                        "draws_per_shot": 2,
                        "h3_anchor_images_per_shot": {"minimum": 3, "maximum": 5},
                        "h3_anchor_density_max_per_shot": 4.1,
                        "h3_prompt_max_characters": 1600,
                        "execution_order": "pipelined_single_generate_single_download",
                        "download_queue_capacity": 4,
                        "expected_width": _FOUR_K_DIMENSIONS[normalized_ratio][0],
                        "expected_height": _FOUR_K_DIMENSIONS[normalized_ratio][1],
                    }
                    if production_contract == GOLD_PRODUCTION_CONTRACT
                    else {}
                ),
            },
            "inheritance_policy": {
                "mode": "fresh_redesign",
                "source_task_id": None,
            },
            "variant_ledger": {
                "approved_generate_set": [],
                "assets": [],
            },
            "shot_plan_approval": {
                "status": (
                    "pending"
                    if deterministic_gates
                    or production_contract == GOLD_PRODUCTION_CONTRACT
                    else "not_required"
                ),
                "approved_at": None,
                "approved_by": None,
            },
            "storyboard_sample_approval": {
                "status": "pending" if production_contract == GOLD_PRODUCTION_CONTRACT else "not_required",
                "approved_at": None,
                "approved_by": None,
            },
            "storyboard_approval": {
                "status": "pending",
                "approved_at": None,
                "approved_by": None,
            },
            "execution": {"mode": execution_mode},
            "budget": {
                "currency": "CNY",
                "hard_limit": budget,
                "estimated": 0.0,
                "spent": 0.0,
                "committed": 0.0,
                "price_source": None,
            },
            "delivery": {
                "status": "planned",
                "human_review": "pending",
                "accepted_at": None,
            },
            "notes": [],
        }
        self.save(payload)
        self.write_status(task_id, "planned", "等待完整语义拆解和镜头计划")
        return payload

    def approve_shot_plan(
        self,
        task_id: str,
        *,
        approval_source: str,
    ) -> dict[str, Any]:
        """Record an explicit user approval over the exact stage-1 review bundle."""

        if approval_source != APPROVAL_SOURCE_EXPLICIT_USER:
            raise BrollTaskError(
                "approve-shot-plan requires approval_source=explicit_user_instruction"
            )
        directory = self.directory(task_id)
        payload = self.load(task_id)
        try:
            plan = json.loads((directory / "shot-plan.json").read_text(encoding="utf-8"))
            visual_lock = json.loads(
                (directory / "visual-lock.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise BrollTaskError(
                "shot-plan approval requires readable visual-lock.json and shot-plan.json"
            ) from exc
        if plan.get("schema_version") != "3.0":
            raise BrollTaskError(
                "approve-shot-plan requires the deterministic shot-plan schema_version 3.0"
            )

        from .producer import (
            shot_plan_approval_snapshot,
            validate_approved_generate_set,
            validate_shot_plan,
        )

        validate_shot_plan(payload, plan)
        planned_ids = [str(item["shot_id"]) for item in plan["shots"]]
        ledger = dict(payload.get("variant_ledger", {}))
        approved_set = ledger.get("approved_generate_set")
        if not approved_set:
            if payload.get("inheritance_policy", {}).get("mode") != "fresh_redesign":
                raise BrollTaskError(
                    "variant tasks must declare approved_generate_set before shot-plan approval"
                )
            ledger["approved_generate_set"] = planned_ids
            payload["variant_ledger"] = ledger
        validate_approved_generate_set(payload, planned_ids, context="shot plan")
        snapshot = shot_plan_approval_snapshot(
            directory, payload, visual_lock=visual_lock, shot_plan=plan
        )
        receipt: dict[str, Any] = {
            "status": "approved",
            "approved_at": now(),
            "approved_by": "user",
            "approval_source": APPROVAL_SOURCE_EXPLICIT_USER,
            **snapshot,
        }
        payload["shot_plan_approval"] = receipt
        self.save(payload)
        self.write_status(
            task_id,
            "shot_plan_approved",
            "用户已明确批准视觉锁与镜头计划；任一字节变化都需要重新批准",
        )
        return payload

    def load(self, task_id: str) -> dict[str, Any]:
        path = self.directory(task_id) / "task.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BrollTaskError(f"task authority is unreadable: {path}") from exc
        self.validate(payload)
        return payload

    def save(self, payload: Mapping[str, Any]) -> None:
        mutable = dict(payload)
        mutable["updated_at"] = now()
        self.validate(mutable)
        directory = self.directory(str(mutable["task_id"]))
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "task.json"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, delete=False) as handle:
            json.dump(mutable, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        temporary.replace(target)

    def approve_storyboards(
        self,
        task_id: str,
        *,
        approved_by: str = "user",
        approval_source: str | None = None,
    ) -> dict[str, Any]:
        if approved_by != "user":
            raise BrollTaskError("storyboards can only be approved by the user")
        if approval_source not in {None, APPROVAL_SOURCE_EXPLICIT_USER}:
            raise BrollTaskError("unsupported storyboard approval source")
        directory = self.directory(task_id)
        manifest = directory / "storyboard-manifest.json"
        if not manifest.is_file():
            raise BrollTaskError("storyboard manifest does not exist")
        from .producer import storyboard_approval_snapshot

        payload = self.load(task_id)
        if (
            payload.get("shot_plan_approval", {}).get("status") != "not_required"
            and approval_source != APPROVAL_SOURCE_EXPLICIT_USER
        ):
            raise BrollTaskError(
                "strict storyboard approval requires an explicit user instruction"
            )
        manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
        snapshot = storyboard_approval_snapshot(directory, manifest_payload)
        receipt = {
            "status": "approved",
            "approved_at": now(),
            "approved_by": "user",
            **snapshot,
        }
        if approval_source is not None:
            receipt["approval_source"] = approval_source
        payload["storyboard_approval"] = receipt
        self.save(payload)
        self.write_status(
            task_id,
            "storyboards_ready",
            "用户已确认 Codex Imagine 故事板；同一 manifest 已冻结语义锚点与 H3 生成脚本",
        )
        return payload

    def approve_storyboard_sample(
        self,
        task_id: str,
        *,
        approved_by: str = "user",
        approval_source: str | None = None,
    ) -> dict[str, Any]:
        if approved_by != "user":
            raise BrollTaskError("storyboard samples can only be approved by the user")
        if approval_source not in {None, APPROVAL_SOURCE_EXPLICIT_USER}:
            raise BrollTaskError("unsupported storyboard sample approval source")
        payload = self.load(task_id)
        if payload.get("spec", {}).get("production_contract") != GOLD_PRODUCTION_CONTRACT:
            raise BrollTaskError("this task does not require the gold storyboard sample gate")
        if (
            payload.get("shot_plan_approval", {}).get("status") != "not_required"
            and approval_source != APPROVAL_SOURCE_EXPLICIT_USER
        ):
            raise BrollTaskError(
                "strict storyboard sample approval requires an explicit user instruction"
            )
        directory = self.directory(task_id)
        sample = directory / "storyboard-sample.json"
        if not sample.is_file():
            raise BrollTaskError("storyboard sample manifest does not exist")
        from .producer import storyboard_sample_approval_snapshot

        try:
            sample_payload = json.loads(sample.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BrollTaskError("storyboard sample manifest is unreadable") from exc
        snapshot = storyboard_sample_approval_snapshot(directory, sample_payload)
        receipt = {
            "status": "approved",
            "approved_at": now(),
            "approved_by": "user",
            **snapshot,
        }
        if approval_source is not None:
            receipt["approval_source"] = approval_source
        payload["storyboard_sample_approval"] = receipt
        self.save(payload)
        self.write_status(task_id, "storyboard_sample_ready", "用户已确认 1-2 个代表性故事板样板")
        return payload

    def authorize_generation(self, task_id: str) -> dict[str, Any]:
        payload = self.load(task_id)
        plan_path = self.directory(task_id) / "generation-plan.json"
        if plan_path.is_file():
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
                frozen_total = round(float(plan["estimated_total_cny"]), 2)
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise BrollTaskError("frozen generation plan is unreadable during authorization") from exc
            if plan.get("task_id") != task_id:
                raise BrollTaskError("frozen generation plan belongs to another task")
            spent = float(payload["budget"]["spent"])
            hard_limit = float(payload["budget"]["hard_limit"])
            if frozen_total <= 0 or spent + frozen_total > hard_limit:
                raise BrollTaskError("frozen generation plan exceeds the task hard budget")
            payload["budget"]["estimated"] = frozen_total
            payload["budget"]["committed"] = frozen_total
        payload["execution"]["mode"] = "authorized"
        self.save(payload)
        self.write_status(task_id, "authorized", "用户已授权在任务硬预算内执行 AutoDL 生成")
        return payload

    def provider_directory(self, task_id: str) -> Path:
        """Return the authoritative AutoDL provider record location."""

        return self.directory(task_id) / "provider" / task_provider(self.load(task_id))

    def attempt_directory(self, task_id: str, shot_id: str, attempt: str) -> Path:
        """Resolve one provider-neutral H3 attempt inside its task boundary."""

        if Path(shot_id).name != shot_id or not shot_id:
            raise BrollTaskError("invalid shot id")
        if Path(attempt).name != attempt or not attempt.startswith("attempt-"):
            raise BrollTaskError("invalid attempt name")
        return self.directory(task_id) / "h3-requests" / shot_id / attempt

    def accept(self, task_id: str) -> dict[str, Any]:
        payload = self.load(task_id)
        directory = self.directory(task_id)
        manifest_path = directory / "delivery-manifest.json"
        if not manifest_path.is_file():
            raise BrollTaskError("no delivered B-roll manifest exists")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BrollTaskError("delivered B-roll manifest is unreadable") from exc
        clips = manifest.get("clips")
        if manifest.get("task_id") != task_id or not isinstance(clips, list) or not clips:
            raise BrollTaskError("delivery manifest has no valid clips")
        accepted_at = now()
        for clip in clips:
            if not isinstance(clip, dict):
                raise BrollTaskError("delivery manifest contains an invalid clip")
            shot_id = str(clip.get("shot_id", ""))
            attempt = str(clip.get("attempt", ""))
            candidate = Path(str(clip.get("path", ""))).expanduser().resolve()
            request_path_value = str(clip.get("request_path", "")).strip()
            if request_path_value:
                request_path = (directory / request_path_value).resolve()
                if (
                    not request_path.is_relative_to(directory.resolve())
                    or request_path.name != "request.json"
                    or request_path.parent.name != attempt
                ):
                    raise BrollTaskError(
                        f"delivery clip has an invalid request path: {shot_id}/{attempt}"
                    )
                result_path = request_path.parent / "result.json"
            else:
                result_path = self.attempt_directory(task_id, shot_id, attempt) / "result.json"
            if not candidate.is_file() or candidate.stat().st_size == 0:
                raise BrollTaskError(f"delivered candidate is missing or empty: {candidate}")
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise BrollTaskError(
                    f"delivery clip has no readable H3 attempt result: {shot_id}/{attempt}"
                ) from exc
            generated = Path(str(result.get("download_path", ""))).expanduser().resolve()
            if (
                result.get("shot_id") != shot_id
                or result.get("attempt") != attempt
                or result.get("provider_status") != "succeeded"
                or not str(result.get("prompt_id", "")).strip()
                or not generated.is_file()
                or generated.stat().st_size == 0
                or result.get("output_sha256") != sha256_file(generated)
                or clip.get("sha256") != sha256_file(candidate)
                or clip.get("source_sha256") != result.get("output_sha256")
            ):
                raise BrollTaskError(
                    f"delivery clip is not backed by a real succeeded H3 attempt: {shot_id}/{attempt}"
                )
            result["human_review"] = "accepted"
            result["accepted_at"] = accepted_at
            _atomic_json(result_path, result)
            clip["human_review"] = "accepted"
            clip["accepted_at"] = accepted_at
            clip["prompt_id"] = result["prompt_id"]
            clip["fingerprint"] = result.get("fingerprint")
        manifest["delivery_status"] = "accepted"
        manifest["human_review"] = "accepted"
        manifest["accepted_at"] = accepted_at
        _atomic_json(manifest_path, manifest)
        payload["delivery"].update(
            {"status": "accepted", "human_review": "accepted", "accepted_at": accepted_at}
        )
        self.save(payload)
        self.write_status(task_id, "accepted", "用户已完成人工审片")
        return payload

    def request_revision(
        self, task_id: str, *, shot_ids: list[str], reason: str
    ) -> dict[str, Any]:
        """Archive the current delivery so fresh H3 attempts can be replanned safely."""

        payload = self.load(task_id)
        if payload.get("spec", {}).get("production_contract") == GOLD_PRODUCTION_CONTRACT:
            raise BrollTaskError(
                "agent-know-gold-v1 does not auto-authorize extra paid draws; "
                "a revision requires a separately approved revision contract"
            )
        directory = self.directory(task_id)
        manifest_path = directory / "delivery-manifest.json"
        if not manifest_path.is_file():
            raise BrollTaskError("revision requires an existing delivered candidate manifest")
        if payload["delivery"].get("human_review") == "accepted":
            raise BrollTaskError("accepted delivery cannot be revised without explicit reopen support")
        normalized = sorted({value.strip() for value in shot_ids if value.strip()})
        if not normalized or not reason.strip():
            raise BrollTaskError("revision requires shot ids and a reason")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        delivered_ids = {
            str(item.get("shot_id")) for item in manifest.get("clips", []) if isinstance(item, dict)
        }
        unknown = sorted(set(normalized) - delivered_ids)
        if unknown:
            raise BrollTaskError("revision names unknown delivered shots: " + ", ".join(unknown))
        archive_root = directory / "delivery-manifests"
        archive_root.mkdir(parents=True, exist_ok=True)
        archives = sorted(archive_root.glob("delivery-*.json"))
        archive = archive_root / f"delivery-{len(archives) + 1:03d}.json"
        manifest["revision_requested_at"] = now()
        manifest["revision_shot_ids"] = normalized
        manifest["revision_reason"] = reason.strip()
        _atomic_json(archive, manifest)
        manifest_path.unlink()
        payload["delivery"].update(
            {"status": "revision_requested", "human_review": "pending", "accepted_at": None}
        )
        payload["budget"]["estimated"] = 0.0
        payload["budget"]["committed"] = 0.0
        payload.setdefault("notes", []).append(
            {
                "at": now(),
                "type": "revision_requested",
                "shot_ids": normalized,
                "reason": reason.strip(),
            }
        )
        self.save(payload)
        self.write_status(
            task_id,
            "revision_requested",
            "已保留旧交付；为指定镜头创建新 attempt 后重新执行 plan-batch",
        )
        return payload

    def write_status(self, task_id: str, state: str, detail: str) -> None:
        target = self.directory(task_id) / "status.md"
        target.write_text(
            f"# 任务状态\n\n- 状态：`{state}`\n- 更新时间：{now()}\n- 说明：{detail}\n",
            encoding="utf-8",
        )

    @staticmethod
    def validate(payload: Mapping[str, Any]) -> None:
        for field in ("task_id", "task_name", "source", "spec", "budget", "storyboard_approval"):
            if field not in payload:
                raise BrollTaskError(f"task authority is missing {field}")
        spec = payload["spec"]
        if spec.get("storyboard_backend") != "codex-imagine":
            raise BrollTaskError("storyboard backend must remain Codex Imagine")
        task_provider(payload)
        _validate_inheritance_authority(payload)
        if spec.get("resolution") not in RESOLUTIONS:
            raise BrollTaskError("only base H3 (768P label) and cloud RTX 4K are supported")
        contract = spec.get("production_contract")
        if contract is not None and contract not in PRODUCTION_CONTRACTS:
            raise BrollTaskError("unsupported production contract")
        if contract == GOLD_PRODUCTION_CONTRACT:
            expected = _FOUR_K_DIMENSIONS.get(str(spec.get("ratio")))
            workflow_contract = spec.get("workflow_contract")
            if (
                spec.get("provider") != "autodl"
                or spec.get("backend") != _PROVIDER_BACKENDS["autodl"]
                or spec.get("resolution") != "4K"
                or spec.get("provider_profile") != "precision_keyframes"
                or spec.get("audio_policy") not in {"silent", "sfx_only"}
                or spec.get("draws_per_shot") not in {1, 2}
                or spec.get("h3_anchor_images_per_shot") != {"minimum": 3, "maximum": 5}
                or spec.get("h3_anchor_density_max_per_shot") != 4.1
                or spec.get("h3_prompt_max_characters") != 1600
                or spec.get("execution_order") != "pipelined_single_generate_single_download"
                or spec.get("download_queue_capacity") != 4
                or not expected
                or (spec.get("expected_width"), spec.get("expected_height")) != expected
                or workflow_contract not in {None, THREE_STAGE_WORKFLOW_CONTRACT}
            ):
                raise BrollTaskError("agent-know-gold-v1 task spec was changed")
            if workflow_contract == THREE_STAGE_WORKFLOW_CONTRACT and spec.get(
                "audio_policy"
            ) != "sfx_only":
                raise BrollTaskError(
                    "three-stage-four-panel-v1 requires the single sfx_only audio policy"
                )
            sample = payload.get("storyboard_sample_approval")
            if not isinstance(sample, Mapping) or sample.get("status") not in {"pending", "approved"}:
                raise BrollTaskError("gold task lacks its storyboard sample gate")
        shot_plan_approval = payload.get("shot_plan_approval")
        if shot_plan_approval is not None:
            if (
                not isinstance(shot_plan_approval, Mapping)
                or shot_plan_approval.get("status")
                not in {"not_required", "pending", "approved"}
            ):
                raise BrollTaskError("task has an invalid shot-plan approval gate")
            if shot_plan_approval.get("status") == "approved":
                if (
                    shot_plan_approval.get("approved_by") != "user"
                    or shot_plan_approval.get("approval_source")
                    != APPROVAL_SOURCE_EXPLICIT_USER
                    or shot_plan_approval.get("approval_scope")
                    != "visual_lock_and_shot_plan"
                    or not re.fullmatch(
                        r"[a-f0-9]{64}",
                        str(shot_plan_approval.get("review_bundle_sha256", "")),
                    )
                    or not re.fullmatch(
                        r"[a-f0-9]{64}",
                        str(shot_plan_approval.get("inheritance_ledger_sha256", "")),
                    )
                    or not isinstance(
                        shot_plan_approval.get("approved_generate_set"), list
                    )
                ):
                    raise BrollTaskError(
                        "approved shot plan lacks a truthful explicit-user review receipt"
                    )
        runtime_overrides = payload.get("runtime_overrides", {})
        if not isinstance(runtime_overrides, Mapping):
            raise BrollTaskError("runtime overrides must be an object")
        if runtime_overrides.get("download_backpressure", "bounded") not in {"bounded", "disabled"}:
            raise BrollTaskError("unsupported download backpressure override")
        shutdown_override = runtime_overrides.get("shutdown_after_success", True)
        if not isinstance(shutdown_override, bool):
            raise BrollTaskError("shutdown-after-success override must be boolean")
        if contract == GOLD_PRODUCTION_CONTRACT:
            if runtime_overrides.get("download_backpressure", "bounded") != "bounded":
                raise BrollTaskError("gold production requires bounded download backpressure")
            if shutdown_override is False:
                handoff = runtime_overrides.get("authorized_handoff")
                if (
                    not isinstance(handoff, Mapping)
                    or handoff.get("authorized_by") != "user"
                    or not str(handoff.get("authorized_at", "")).strip()
                    or not str(handoff.get("next_task_id", "")).strip()
                ):
                    raise BrollTaskError(
                        "keeping the GPU alive requires an explicit user-authorized next-task handoff"
                    )
        budget = payload["budget"]
        if not 0 < float(budget.get("hard_limit", 0)) <= MAX_BUDGET_CNY:
            raise BrollTaskError("invalid hard budget limit")


def _validate_inheritance_authority(payload: Mapping[str, Any]) -> None:
    policy = payload.get("inheritance_policy")
    ledger = payload.get("variant_ledger")
    if policy is None and ledger is None:
        return
    if not isinstance(policy, Mapping) or policy.get("mode") not in INHERITANCE_MODES:
        raise BrollTaskError("inheritance_policy has an unsupported mode")
    source_task_id = policy.get("source_task_id")
    if source_task_id is not None and not str(source_task_id).strip():
        raise BrollTaskError("inheritance_policy source_task_id must be non-empty or null")
    if policy.get("mode") != "fresh_redesign" and not str(source_task_id or "").strip():
        raise BrollTaskError("non-fresh inheritance requires source_task_id")
    if not isinstance(ledger, Mapping):
        raise BrollTaskError("variant_ledger must be an object")
    generate_set = ledger.get("approved_generate_set")
    assets = ledger.get("assets")
    if (
        not isinstance(generate_set, list)
        or any(not isinstance(value, str) or not value.strip() for value in generate_set)
        or len(generate_set) != len(set(generate_set))
    ):
        raise BrollTaskError("variant_ledger approved_generate_set must contain unique shot ids")
    if not isinstance(assets, list):
        raise BrollTaskError("variant_ledger assets must be an array")
    asset_ids: set[str] = set()
    for item in assets:
        if not isinstance(item, Mapping):
            raise BrollTaskError("variant ledger assets must be objects")
        asset_id = str(item.get("asset_id", "")).strip()
        if not asset_id or asset_id in asset_ids:
            raise BrollTaskError("variant ledger asset_id must be non-empty and unique")
        asset_ids.add(asset_id)
        if item.get("disposition") not in ASSET_DISPOSITIONS:
            raise BrollTaskError("variant ledger asset has an invalid disposition")
        if item.get("variant_role") not in ASSET_VARIANT_ROLES:
            raise BrollTaskError("variant ledger asset has an invalid variant_role")
        shot_id = item.get("shot_id")
        if shot_id is not None and not str(shot_id).strip():
            raise BrollTaskError("variant ledger shot_id must be non-empty when supplied")


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)
