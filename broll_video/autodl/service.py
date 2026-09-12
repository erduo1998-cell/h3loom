"""Small, direct AutoDL production path.

Everything that can be proved locally is frozen by :meth:`plan_batch`. A live
run never replans and never repeats the launch script's Comfy readiness probe.
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
import fcntl
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid4, uuid5

from broll_video.producer import (
    current_attempts,
    validate_approved_request_media,
    validate_storyboard_approval,
    validate_storyboard_manifest,
)
from broll_video.requests import load_request, request_to_dict
from broll_video.h3.models import H3InputError
from broll_video.h3.prompt_gate import validate_h3_upload_gate
from broll_video.task import (
    GOLD_PRODUCTION_CONTRACT,
    THREE_STAGE_WORKFLOW_CONTRACT,
    BrollTaskError,
    BrollTaskStore,
    now,
    task_provider,
)
from .graph import FOUR_K_DIMENSIONS

from .pricing import AutoDLPricingCatalog
from .readiness import (
    GoldenStackFingerprint,
    GoldenStackPolicy,
    validate_golden_runtime_evidence,
    validate_golden_stack,
)
from .workflow import (
    AutoDLWorkflowCompiler,
    compiled_workflow_evidence,
    final_conditioning_evidence,
)


class AutoDLProductionError(RuntimeError):
    pass


class BrollAutoDLService:
    """Offline planner plus one direct AutoDL batch runner."""

    PROVIDER_KEY = "autodl"
    PROVIDER_BACKEND = "autodl-comfy-h3"
    GOLD_DOWNLOAD_QUEUE_CAPACITY = 4

    def __init__(
        self,
        tasks: BrollTaskStore,
        pricing: AutoDLPricingCatalog,
        client: Any,
        *,
        project_root: Path | str,
        golden_stack: GoldenStackPolicy,
        **_: Any,
    ) -> None:
        self.tasks = tasks
        self.pricing = pricing
        self.client = client
        self.project_root = Path(project_root).expanduser().resolve()
        self.golden_stack = golden_stack

    # Everything in this section is local and runs while the GPU is off.
    def plan_batch(self, task_id: str, *, recover_only: bool = False) -> dict[str, Any]:
        if recover_only:
            return self._load_existing_plan(task_id)
        task = self.tasks.load(task_id)
        if (
            task.get("spec", {}).get("production_contract") != GOLD_PRODUCTION_CONTRACT
            or task.get("spec", {}).get("workflow_contract")
            != THREE_STAGE_WORKFLOW_CONTRACT
        ):
            raise BrollTaskError(
                "AutoDL paid planning accepts only the current three-stage gold contract"
            )
        directory = self.tasks.directory(task_id)
        requests = self._approved_requests(task_id)
        total = Decimal("0")
        items: list[dict[str, Any]] = []
        for item in requests:
            quote = self.pricing.quote_request(item["request"])
            total += quote
            items.append(
                {
                    "shot_id": item["shot_id"],
                    "attempt": item["attempt"],
                    "request_path": str(Path(item["request_path"]).relative_to(directory)),
                    "fingerprint": item["fingerprint"],
                    "legacy_fingerprint": item["legacy_fingerprint"],
                    "compiled_workflow_sha256": item["compiled_workflow_sha256"],
                    "compiler_manifest": item["compiler_manifest"],
                    "profile": item["request"].provider_profile,
                    "rtx_target_frame_count_canary": item["rtx_target_frame_count_canary"],
                    "estimated_cost_cny": str(quote),
                    **(
                        {"replacement_lineage": dict(item["replacement_lineage"])}
                        if isinstance(item.get("replacement_lineage"), Mapping)
                        else {}
                    ),
                }
            )
        total = total.quantize(Decimal("0.01"))
        spent = Decimal(str(task["budget"]["spent"]))
        hard_limit = Decimal(str(task["budget"]["hard_limit"]))
        if spent + total > hard_limit:
            raise BrollTaskError("AutoDL batch exceeds the authorized task budget")
        plan = {
            "schema_version": "3.0",
            "task_id": task_id,
            "provider": self.PROVIDER_BACKEND,
            "storyboard_approval_at": task["storyboard_approval"]["approved_at"],
            "pricing_source": self.pricing.source_reference,
            "estimated_total_cny": str(total),
            "created_at": now(),
            "items": items,
        }
        plan_path = directory / "generation-plan.json"
        if plan_path.is_file():
            prior = json.loads(plan_path.read_text(encoding="utf-8"))
            if _logical_items(prior) != _logical_items(plan):
                prior_paths = {
                    str(item.get("request_path", "")) for item in prior.get("items", [])
                }
                new_paths = {
                    str(item.get("request_path", "")) for item in plan.get("items", [])
                }
                if prior_paths & new_paths and not _plan_change_is_authorized_replacement(
                    prior, plan
                ):
                    raise BrollTaskError(
                        "frozen AutoDL plan changed without fresh attempt paths"
                    )
                _archive_plan_and_live_run(directory, prior)
                _write_json(plan_path, plan)
            else:
                plan = prior
        else:
            _write_json(plan_path, plan)
        task["budget"].update(
            {
                "estimated": float(total),
                "committed": float(total)
                if task["execution"]["mode"] == "authorized"
                else 0.0,
                "price_source": self.pricing.source_reference,
            }
        )
        self.tasks.save(task)
        self._write_live_manifest(task_id, plan)
        self.tasks.write_status(
            task_id,
            "ready_for_live_run"
            if task["execution"]["mode"] == "authorized"
            else "planned",
            "所有本地检查已冻结；开机后只执行提交、等待、下载和关机",
        )
        return plan

    def export_final_conditioning(self, task_id: str) -> dict[str, Any]:
        """Return a read-only audit export of the exact Comfy conditioning.

        The immutable stage-two script remains identified as an input source;
        ``final_conditioning`` is extracted after workflow compilation from the
        node that is actually sent to Comfy.  This method has no provider I/O
        and writes no task artifacts.
        """

        directory = self.tasks.directory(task_id)
        items = self._approved_requests(task_id)
        exports: list[dict[str, Any]] = []
        for item in items:
            request_path = _inside(directory, Path(item["request_path"]))
            evidence = final_conditioning_evidence(item["compiled"])
            workflow = compiled_workflow_evidence(item["compiled"])
            exported: dict[str, Any] = {
                "shot_id": item["shot_id"],
                "attempt": item["attempt"],
                "request_path": str(request_path.relative_to(directory)),
                "stage_two_generation_script": {
                    "label": "frozen_stage_two_generation_script_not_final_conditioning",
                    "sha256": hashlib.sha256(
                        item["request"].prompt.encode("utf-8")
                    ).hexdigest(),
                },
                "compiled_workflow_sha256": workflow["compiled_workflow_sha256"],
                **evidence,
            }
            if isinstance(item.get("replacement_lineage"), Mapping):
                exported["replacement_lineage"] = dict(item["replacement_lineage"])
            exports.append(exported)
        payload = {
            "schema_version": "autodl-final-conditioning-export-v1",
            "artifact_type": "final_h3_conditioning",
            "read_only": True,
            "task_id": task_id,
            "source": "compiled AutoDL Comfy workflow, before upload and /prompt submission",
            "items": exports,
        }
        payload["export_sha256"] = _canonical_sha256(payload)
        return payload

    def authorize_replacement(
        self,
        task_id: str,
        *,
        shot_id: str,
        attempt: str,
        reason: str,
        recovery_evidence: str,
        authorized_by: str = "user",
    ) -> dict[str, Any]:
        """Record explicit user authorization to replace one unrecoverable live attempt.

        A normal SSH interruption never reaches this state.  The old provider
        record must contain a prompt id and a concrete instance, so its original
        recovery route stays intact and auditable.
        """

        if authorized_by != "user":
            raise BrollTaskError("replacement can only be authorized by the user")
        if not reason.strip() or not recovery_evidence.strip():
            raise BrollTaskError(
                "replacement authorization requires a reason and unrecoverable-instance evidence"
            )
        if not _attempt_name_is_valid(attempt):
            raise BrollTaskError("replacement authorization has an invalid old attempt name")
        task = self.tasks.load(task_id)
        if task.get("execution", {}).get("mode") != "authorized":
            raise BrollTaskError("replacement requires an already authorized generation task")
        if task.get("spec", {}).get("production_contract") != GOLD_PRODUCTION_CONTRACT:
            raise BrollTaskError("replacement is reserved for the active gold production contract")
        directory = self.tasks.directory(task_id)
        from broll_video.gold_contract import validate_gold_request_set

        try:
            manifest = json.loads(
                (directory / "storyboard-manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise BrollTaskError("replacement authorization requires the frozen storyboard manifest") from exc
        approved = validate_gold_request_set(task, directory, manifest)
        if shot_id not in approved:
            raise BrollTaskError("replacement authorization refers to an unapproved shot")
        request_path = directory / "h3-requests" / shot_id / attempt / "request.json"
        if request_path not in approved[shot_id]:
            raise BrollTaskError("replacement authorization refers to a non-canonical old attempt")
        request = load_request(request_path, expected_provider="autodl")
        compiled = AutoDLWorkflowCompiler().compile(request)
        try:
            validate_h3_upload_gate(request, compiled)
        except H3InputError as exc:
            raise BrollTaskError(f"replacement source failed the H3 prompt hard gate: {exc}") from exc
        fingerprint = _production_fingerprint(compiled, self._approved_stack())
        record_path = directory / "provider" / self.PROVIDER_KEY / f"{fingerprint}.json"
        record = _read_json(record_path)
        if record is None:
            raise BrollTaskError("replacement requires the original durable provider record")
        prompt_id = str(record.get("prompt_id", "")).strip()
        old_instance_id = str(record.get("instance_id", "")).strip()
        if not prompt_id or not old_instance_id:
            raise BrollTaskError(
                "replacement requires an old prompt_id and old instance; unresolved submission cannot be replaced"
            )
        if record.get("status") == "succeeded":
            raise BrollTaskError("a succeeded prompt is recoverable and cannot be replaced")
        task_id_path = request_path.parent / "task-id.txt"
        task_prompt_id = (
            task_id_path.read_text(encoding="utf-8").strip()
            if task_id_path.is_file()
            else ""
        )
        if task_prompt_id and task_prompt_id != prompt_id:
            raise BrollTaskError("old provider record and task-id.txt disagree")
        for existing in _replacement_authorizations(directory):
            old = existing.get("old_attempt", {})
            if (
                existing.get("state") in {"authorized", "live_attempt_created"}
                and old.get("shot_id") == shot_id
                and old.get("attempt") == attempt
            ):
                raise BrollTaskError("this old attempt already has an active replacement authorization")
        authorization_id = f"replacement-{uuid4().hex}"
        authorization = {
            "schema_version": "autodl-replacement-v1",
            "authorization_id": authorization_id,
            "task_id": task_id,
            "state": "authorized",
            "authorized_at": now(),
            "authorization_scope": {
                "authorized_by": "user",
                "reason": reason.strip(),
                "old_instance_unrecoverable": True,
                "recovery_evidence": recovery_evidence.strip(),
            },
            "old_attempt": {
                "shot_id": shot_id,
                "attempt": attempt,
                "request_path": str(request_path.relative_to(directory)),
                "request_sha256": _sha256_file(request_path),
                "fingerprint": fingerprint,
                "prompt_id": prompt_id,
                "instance_id": old_instance_id,
                "instance_context": (
                    dict(record["instance_context"])
                    if isinstance(record.get("instance_context"), Mapping)
                    else None
                ),
                "provider_record_path": str(record_path.relative_to(directory)),
                "provider_record_sha256": _sha256_file(record_path),
            },
        }
        target = _replacement_authorization_path(directory, authorization_id)
        _write_json_exclusive(target, authorization)
        return authorization

    def replace_live_attempt(
        self,
        task_id: str,
        authorization_id: str,
        *,
        new_instance_context: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Create one new, lineage-bound attempt after explicit authorization.

        This local state transition does not upload or submit anything.  A
        subsequent offline ``plan-batch`` freezes the new request, and only
        ``run-batch`` may submit it.  The old record is never moved, edited, or
        reused as the new attempt.
        """

        task = self.tasks.load(task_id)
        directory = self.tasks.directory(task_id)
        authorization_path = _replacement_authorization_path(directory, authorization_id)
        authorization = _read_json(authorization_path)
        if authorization is None or authorization.get("task_id") != task_id:
            raise BrollTaskError("replacement authorization is missing or belongs to another task")
        if authorization.get("state") != "authorized":
            raise BrollTaskError("replacement authorization is not awaiting a new live attempt")
        if authorization.get("authorization_scope", {}).get("authorized_by") != "user":
            raise BrollTaskError("replacement authorization is not user-approved")
        if authorization.get("authorization_scope", {}).get("old_instance_unrecoverable") is not True:
            raise BrollTaskError("replacement authorization lacks unrecoverable-instance confirmation")
        old = authorization.get("old_attempt")
        if not isinstance(old, Mapping):
            raise BrollTaskError("replacement authorization has no old-attempt lineage")
        old_record_path = _inside(directory, directory / str(old.get("provider_record_path", "")))
        old_record = _read_json(old_record_path)
        if (
            old_record is None
            or _sha256_file(old_record_path) != str(old.get("provider_record_sha256", ""))
            or str(old_record.get("prompt_id", "")).strip() != str(old.get("prompt_id", "")).strip()
            or str(old_record.get("instance_id", "")).strip() != str(old.get("instance_id", "")).strip()
        ):
            raise BrollTaskError("old provider lineage changed; stop instead of creating a replacement")
        if old_record.get("status") == "succeeded":
            raise BrollTaskError("old prompt is now recoverable and cannot be replaced")
        old_request_path = _inside(directory, directory / str(old.get("request_path", "")))
        if _sha256_file(old_request_path) != str(old.get("request_sha256", "")):
            raise BrollTaskError("old frozen request changed; stop instead of creating a replacement")
        old_request = load_request(old_request_path, expected_provider="autodl")
        context = _normalize_instance_context(new_instance_context, require_endpoint=True)
        old_context = old.get("instance_context")
        if context["provider_instance_id"] == str(old.get("instance_id", "")).strip():
            raise BrollTaskError("replacement target must differ from the old instance")
        if isinstance(old_context, Mapping) and context == _normalize_instance_context(
            old_context, require_endpoint=True
        ):
            raise BrollTaskError("replacement target must differ from the old instance context")
        old_attempt = str(old.get("attempt", ""))
        shot_id = str(old.get("shot_id", ""))
        if not shot_id or not _attempt_name_is_valid(old_attempt):
            raise BrollTaskError("replacement authorization has invalid old-attempt scope")
        new_attempt = _next_replacement_attempt_name(directory, shot_id)
        new_seed = _replacement_seed(str(old.get("fingerprint", "")), authorization_id)
        replacement = replace(old_request, seed=new_seed)
        replacement_path = (
            directory / "h3-replacements" / shot_id / new_attempt / "request.json"
        )
        _write_json_exclusive(
            replacement_path,
            request_to_dict(replacement, provider="autodl"),
        )
        new_lineage = {
            "authorization_id": authorization_id,
            "created_at": now(),
            "shot_id": shot_id,
            "attempt": new_attempt,
            "request_path": str(replacement_path.relative_to(directory)),
            "request_sha256": _sha256_file(replacement_path),
            "seed": new_seed,
            "replaces": {
                "attempt": old_attempt,
                "prompt_id": old["prompt_id"],
                "instance_id": old["instance_id"],
                "fingerprint": old["fingerprint"],
            },
            "new_instance_context": context,
        }
        authorization.update({"state": "live_attempt_created", "new_attempt": new_lineage})
        _write_json(authorization_path, authorization)
        return {
            **authorization,
            "next": f"broll-autodl plan-batch {task_id}",
        }

    def current_instance_context(self) -> dict[str, Any]:
        """Read the configured instance identity without starting or probing Comfy."""

        return _instance_lock_context(self.client.instance(), self.client)

    def _approved_requests(self, task_id: str) -> list[dict[str, Any]]:
        task = self.tasks.load(task_id)
        if task_provider(task) != self.PROVIDER_KEY:
            raise BrollTaskError("task is not bound to AutoDL")
        if task["storyboard_approval"]["status"] != "approved":
            raise BrollTaskError("storyboards require user approval before planning")
        directory = self.tasks.directory(task_id)
        try:
            manifest = json.loads(
                (directory / "storyboard-manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise BrollTaskError("storyboard manifest is missing or invalid") from exc
        validate_storyboard_manifest(directory, manifest)
        validate_storyboard_approval(task, directory, manifest)
        active_gold_attempts: dict[str, list[Path]] | None = None
        if task.get("spec", {}).get("production_contract") == GOLD_PRODUCTION_CONTRACT:
            from broll_video.gold_contract import validate_gold_request_set

            active_gold_attempts = validate_gold_request_set(
                task, directory, manifest
            )
        shot_ids = [str(item["shot_id"]) for item in manifest["shots"]]
        draws_value = task.get("spec", {}).get("draws_per_shot")
        if draws_value not in {1, 2}:
            raise BrollTaskError("task authority requires draws_per_shot=1 or 2")
        draws_per_shot = int(draws_value)
        attempts: dict[str, list[Path]] = {shot_id: [] for shot_id in shot_ids}
        if active_gold_attempts is not None:
            attempts = {
                shot_id: sorted(active_gold_attempts[shot_id]) for shot_id in shot_ids
            }
        else:
            for request_path in sorted(directory.glob("h3-requests/*/attempt-*/request.json")):
                shot_id = request_path.parent.parent.name
                if shot_id not in attempts:
                    raise BrollTaskError(f"H3 request refers to an unapproved shot: {shot_id}")
                attempts[shot_id].append(request_path)
        if any(len(attempts[shot_id]) != draws_per_shot for shot_id in shot_ids):
            raise BrollTaskError("H3 attempts must exactly match approved storyboard shots")
        compiler = AutoDLWorkflowCompiler()
        stack = self._approved_stack()
        result: list[dict[str, Any]] = []
        for shot_id in shot_ids:
            for request_path in attempts[shot_id]:
                request = load_request(request_path, expected_provider="autodl")
                if request.production_contract != task.get("spec", {}).get(
                    "production_contract"
                ):
                    raise BrollTaskError(f"{shot_id} production contract differs from task authority")
                if request.ratio != task["spec"]["ratio"]:
                    raise BrollTaskError(f"{shot_id} ratio differs from task authority")
                if request.resolution != task["spec"]["resolution"]:
                    raise BrollTaskError(f"{shot_id} resolution differs from task authority")
                validate_approved_request_media(directory, manifest, shot_id, request)
                compiled = compiler.compile(request)
                try:
                    validate_h3_upload_gate(request, compiled)
                except H3InputError as exc:
                    raise BrollTaskError(f"{shot_id} failed the H3 prompt hard gate: {exc}") from exc
                evidence = compiled_workflow_evidence(compiled)
                canary = _offline_rtx_canary(compiled)
                if request.resolution == "4K" and canary.get("passed") is not True:
                    raise BrollTaskError(f"{shot_id} failed the offline RTX graph check")
                manifest_data = {
                    **dict(evidence["compiler_manifest"]),
                    "provider": self.PROVIDER_BACKEND,
                    "golden_stack_fingerprint": stack.fingerprint_sha256,
                    "golden_runtime_evidence_sha256": stack.golden_runtime_evidence_sha256,
                    "golden_stack_version": stack.fingerprint_version,
                }
                result.append(
                    {
                        "shot_id": shot_id,
                        "attempt": request_path.parent.name,
                        "request_path": str(request_path),
                        "request": request,
                        "compiled": compiled,
                        "fingerprint": _production_fingerprint(compiled, stack),
                        "legacy_fingerprint": compiled.fingerprint,
                        "compiled_workflow_sha256": evidence["compiled_workflow_sha256"],
                        "compiler_manifest": manifest_data,
                        "rtx_target_frame_count_canary": canary,
                    }
                )
        return self._apply_active_replacements(task_id, task, directory, manifest, result)

    def _apply_active_replacements(
        self,
        task_id: str,
        task: Mapping[str, Any],
        directory: Path,
        manifest: Mapping[str, Any],
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Overlay formally-created replacement attempts onto frozen plan inputs."""

        active = [
            value
            for value in _replacement_authorizations(directory)
            if value.get("task_id") == task_id and value.get("state") == "live_attempt_created"
        ]
        if not active:
            return items
        by_old_attempt = {
            (str(item["shot_id"]), str(item["attempt"])): index
            for index, item in enumerate(items)
        }
        compiler = AutoDLWorkflowCompiler()
        stack = self._approved_stack()
        result = list(items)
        for authorization in active:
            old = authorization.get("old_attempt")
            lineage = authorization.get("new_attempt")
            if not isinstance(old, Mapping) or not isinstance(lineage, Mapping):
                raise BrollTaskError("replacement authorization lineage is invalid")
            key = (str(old.get("shot_id", "")), str(old.get("attempt", "")))
            if key not in by_old_attempt:
                raise BrollTaskError("replacement authorization no longer matches a frozen attempt")
            old_item = result[by_old_attempt[key]]
            replacement_path = _inside(
                directory, directory / str(lineage.get("request_path", ""))
            )
            if _sha256_file(replacement_path) != str(lineage.get("request_sha256", "")):
                raise BrollTaskError("replacement request changed after its authorization")
            old_request = old_item["request"]
            replacement_request = load_request(replacement_path, expected_provider="autodl")
            expected = request_to_dict(
                replace(old_request, seed=int(lineage.get("seed"))), provider="autodl"
            )
            try:
                actual = json.loads(replacement_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise BrollTaskError("replacement request is unreadable") from exc
            if actual != expected:
                raise BrollTaskError(
                    "replacement request must be a newly seeded copy of the immutable old request"
                )
            validate_approved_request_media(
                directory, manifest, str(old_item["shot_id"]), replacement_request
            )
            compiled = compiler.compile(replacement_request)
            try:
                validate_h3_upload_gate(replacement_request, compiled)
            except H3InputError as exc:
                raise BrollTaskError(
                    f"replacement {old_item['shot_id']} failed the H3 prompt hard gate: {exc}"
                ) from exc
            evidence = compiled_workflow_evidence(compiled)
            canary = _offline_rtx_canary(compiled)
            if replacement_request.resolution == "4K" and canary.get("passed") is not True:
                raise BrollTaskError("replacement request failed the offline RTX graph check")
            replacement_attempt = str(lineage.get("attempt", ""))
            if not _attempt_name_is_valid(replacement_attempt):
                raise BrollTaskError("replacement authorization has an invalid new attempt name")
            if any(
                value is not authorization
                and value.get("state") == "live_attempt_created"
                and isinstance(value.get("new_attempt"), Mapping)
                and value["new_attempt"].get("attempt") == replacement_attempt
                and value["new_attempt"].get("shot_id") == old_item["shot_id"]
                for value in active
            ):
                raise BrollTaskError("multiple replacement authorizations claim the same new attempt")
            replacement_lineage = {
                "authorization_id": authorization["authorization_id"],
                "old_attempt": dict(old),
                "new_instance_context": dict(lineage["new_instance_context"]),
            }
            result[by_old_attempt[key]] = {
                **old_item,
                "attempt": replacement_attempt,
                "request_path": str(replacement_path),
                "request": replacement_request,
                "compiled": compiled,
                "fingerprint": _production_fingerprint(compiled, stack),
                "legacy_fingerprint": compiled.fingerprint,
                "compiled_workflow_sha256": evidence["compiled_workflow_sha256"],
                "compiler_manifest": {
                    **dict(evidence["compiler_manifest"]),
                    "provider": self.PROVIDER_BACKEND,
                    "golden_stack_fingerprint": stack.fingerprint_sha256,
                    "golden_runtime_evidence_sha256": stack.golden_runtime_evidence_sha256,
                    "golden_stack_version": stack.fingerprint_version,
                },
                "rtx_target_frame_count_canary": canary,
                "replacement_lineage": replacement_lineage,
            }
        return result

    def _write_live_manifest(self, task_id: str, plan: Mapping[str, Any]) -> Path:
        directory = self.tasks.directory(task_id)
        plan_path = directory / "generation-plan.json"
        entries = []
        for item in plan["items"]:
            request_path = _inside(directory, directory / str(item["request_path"]))
            entries.append(
                {
                    "shot_id": item["shot_id"],
                    "attempt": item["attempt"],
                    "request_path": item["request_path"],
                    "request_sha256": _sha256_file(request_path),
                    "fingerprint": item["fingerprint"],
                    "compiled_workflow_sha256": item["compiled_workflow_sha256"],
                    "estimated_cost_cny": item["estimated_cost_cny"],
                    **(
                        {"replacement_lineage": dict(item["replacement_lineage"])}
                        if isinstance(item.get("replacement_lineage"), Mapping)
                        else {}
                    ),
                }
            )
        payload = {
            "schema_version": "1.0",
            "task_id": task_id,
            "provider": self.PROVIDER_BACKEND,
            "prepared_at": now(),
            "generation_plan_sha256": _sha256_file(plan_path),
            "items": entries,
        }
        target = directory / "live-run.json"
        _write_json(target, payload)
        return target

    # Live path: no replanning, readiness crawl, live pricing or control API.
    def run_batch(
        self,
        task_id: str,
        *,
        shutdown_after: bool = True,
        poll_interval: float = 10.0,
        timeout_per_task: float = 1800.0,
        **_: Any,
    ) -> list[dict[str, Any]]:
        existing = self._completed_results(task_id)
        if existing is not None:
            return existing
        task, items = self._load_live_batch(task_id)
        runtime_overrides = task.get("runtime_overrides", {})
        if (
            isinstance(runtime_overrides, Mapping)
            and runtime_overrides.get("shutdown_after_success") is False
        ):
            shutdown_after = False
        success = False
        started_at = datetime.now(timezone.utc)
        results: list[dict[str, Any]] = []
        try:
            durable_recovery = self._all_items_have_saved_outputs(task_id, items)
            if not durable_recovery:
                # launch-comfy.sh already waits for Comfy. Do not repeat /system_stats.
                self.client.start()
            session = (
                nullcontext(self.client)
                if durable_recovery or not hasattr(self.client, "session")
                else self.client.session()
            )
            with session:
                info = self.client.instance()
                lease_instance_context = _instance_lock_context(info, self.client)
                _validate_replacement_instance_context(items, lease_instance_context)
                with _instance_submission_lease(
                    self.project_root, lease_instance_context, task_id
                ):
                    if task.get("spec", {}).get("production_contract") == GOLD_PRODUCTION_CONTRACT:
                        results = self._run_gold_pipeline(
                            task_id,
                            task,
                            items,
                            info,
                            poll_interval=poll_interval,
                            timeout_per_task=timeout_per_task,
                        )
                    else:
                        for item in items:
                            result = self._run_item(
                                task_id,
                                task,
                                item,
                                info,
                                poll_interval=poll_interval,
                                timeout=timeout_per_task,
                            )
                            results.append(result)
            legacy_unsubmitted = task.get("_legacy_unsubmitted_items", [])
            if legacy_unsubmitted:
                self.tasks.write_status(
                    task_id,
                    "legacy_recovery_partial",
                    f"已恢复 {len(results)} 个已有 prompt_id；另有 {len(legacy_unsubmitted)} 个从未提交的旧请求，必须迁移并重新批准",
                )
            else:
                self._deliver(task_id, results)
            success = True
            return results
        finally:
            # The user's scarce manually acquired GPU stays available for a
            # direct repair on every incomplete run. Automatic shutdown belongs
            # only to a fully downloaded and delivered batch.
            if shutdown_after and success:
                receipt = dict(self.client.shutdown_and_wait())
                self._record_shutdown(task_id, receipt, started_at)
                if receipt.get("shutdown_verified") is not True:
                    raise AutoDLProductionError("AutoDL shutdown could not be verified")

    def _run_gold_pipeline(
        self,
        task_id: str,
        task: dict[str, Any],
        items: list[dict[str, Any]],
        info: Any,
        *,
        poll_interval: float,
        timeout_per_task: float,
    ) -> list[dict[str, Any]]:
        """Keep one GPU generation line and one ordered download/receipt line busy."""

        capacity = int(task.get("spec", {}).get("download_queue_capacity", 0))
        if capacity != self.GOLD_DOWNLOAD_QUEUE_CAPACITY:
            raise BrollTaskError("gold download queue capacity differs from the production contract")
        runtime_overrides = task.get("runtime_overrides", {})
        download_backpressure = (
            runtime_overrides.get("download_backpressure", "bounded")
            if isinstance(runtime_overrides, Mapping)
            else "bounded"
        )
        if download_backpressure != "bounded":
            raise BrollTaskError("gold production requires the bounded download queue")
        pending: deque[tuple[int, Future[dict[str, Any]]]] = deque()
        completed: dict[int, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="broll-download") as downloads:
            for index, item in enumerate(items):
                self._drain_completed_downloads(pending, completed)
                if download_backpressure == "bounded":
                    while len(pending) >= capacity:
                        self._collect_oldest_download(pending, completed)
                output, prompt_id = self._generate_item(
                    task_id,
                    item,
                    info,
                    poll_interval=poll_interval,
                    timeout=timeout_per_task,
                )
                # If the network line failed while the GPU was working, stop
                # before another paid submission. The just-finished output is
                # already durable in the provider record and resumes without a resubmit.
                self._drain_completed_downloads(pending, completed)
                pending.append(
                    (
                        index,
                        downloads.submit(
                            self._download_item,
                            task_id,
                            task,
                            item,
                            info,
                            output=output,
                            prompt_id=prompt_id,
                        ),
                    )
                )
            while pending:
                self._collect_oldest_download(pending, completed)
        return [completed[index] for index in range(len(items))]

    @staticmethod
    def _drain_completed_downloads(
        pending: deque[tuple[int, Future[dict[str, Any]]]],
        completed: dict[int, dict[str, Any]],
    ) -> None:
        while pending and pending[0][1].done():
            BrollAutoDLService._collect_oldest_download(pending, completed)

    @staticmethod
    def _collect_oldest_download(
        pending: deque[tuple[int, Future[dict[str, Any]]]],
        completed: dict[int, dict[str, Any]],
    ) -> None:
        index, future = pending.popleft()
        completed[index] = future.result()

    def _all_items_have_saved_outputs(
        self, task_id: str, items: list[dict[str, Any]]
    ) -> bool:
        directory = self.tasks.directory(task_id)
        for item in items:
            fingerprint = str(item.get("fingerprint", "")).strip()
            if not fingerprint:
                return False
            record = _read_json(
                directory
                / "provider"
                / self.PROVIDER_KEY
                / f"{fingerprint}.json"
            )
            if (
                not record
                or record.get("status") != "succeeded"
                or not isinstance(record.get("output"), Mapping)
            ):
                return False
        return True

    def _load_live_batch(
        self, task_id: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        task = self.tasks.load(task_id)
        directory = self.tasks.directory(task_id)
        if task_provider(task) != self.PROVIDER_KEY:
            raise BrollTaskError("task is not bound to AutoDL")
        current_contract = (
            task.get("spec", {}).get("production_contract") == GOLD_PRODUCTION_CONTRACT
            and task.get("spec", {}).get("workflow_contract")
            == THREE_STAGE_WORKFLOW_CONTRACT
        )
        if task["execution"]["mode"] != "authorized":
            raise BrollTaskError("generation is not authorized")
        if task["storyboard_approval"]["status"] != "approved":
            raise BrollTaskError("storyboards are not approved")
        try:
            live = json.loads((directory / "live-run.json").read_text(encoding="utf-8"))
            plan = json.loads((directory / "generation-plan.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BrollTaskError(
                "offline live-run manifest is missing; run plan-batch while off"
            ) from exc
        if live.get("generation_plan_sha256") != _sha256_file(
            directory / "generation-plan.json"
        ):
            raise BrollTaskError("generation plan changed after offline preparation")
        if live.get("task_id") != task_id or live.get("provider") != self.PROVIDER_BACKEND:
            raise BrollTaskError("live-run manifest belongs to another task or provider")
        plan_by_key = {
            (str(item["shot_id"]), str(item["attempt"])): item
            for item in plan.get("items", [])
        }
        compiler = AutoDLWorkflowCompiler()
        stack = self._approved_stack()
        items: list[dict[str, Any]] = []
        legacy_unsubmitted: list[str] = []
        for frozen in live.get("items", []):
            key = (str(frozen["shot_id"]), str(frozen["attempt"]))
            planned = plan_by_key.get(key)
            if planned is None:
                raise BrollTaskError("live-run item is absent from generation plan")
            request_path = _inside(directory, directory / str(frozen["request_path"]))
            if _sha256_file(request_path) != frozen["request_sha256"]:
                raise BrollTaskError("request changed after offline preparation")
            request = load_request(request_path, expected_provider="autodl")
            provider_record = _read_json(
                directory / "provider" / self.PROVIDER_KEY / f"{frozen['fingerprint']}.json"
            )
            task_id_path = request_path.parent / "task-id.txt"
            saved_prompt_id = (
                str(provider_record.get("prompt_id", "")).strip()
                if provider_record
                else ""
            )
            task_file_prompt_id = (
                task_id_path.read_text(encoding="utf-8").strip()
                if task_id_path.is_file()
                else ""
            )
            if saved_prompt_id and task_file_prompt_id and saved_prompt_id != task_file_prompt_id:
                raise BrollTaskError(
                    f"{key[0]}/{key[1]} provider record and task-id.txt disagree"
                )
            if not saved_prompt_id:
                saved_prompt_id = task_file_prompt_id
            if saved_prompt_id:
                items.append(
                    {
                        **dict(frozen),
                        "request_path_absolute": request_path,
                        "request": request,
                        "compiled": None,
                        "recovery_only": True,
                        "saved_prompt_id": saved_prompt_id,
                    }
                )
                continue
            if not current_contract:
                legacy_unsubmitted.append(f"{key[0]}/{key[1]}")
                continue
            compiled = compiler.compile(request)
            try:
                validate_h3_upload_gate(request, compiled)
            except H3InputError as exc:
                raise BrollTaskError(
                    f"{key[0]} failed the live H3 prompt hard gate: {exc}"
                ) from exc
            evidence = compiled_workflow_evidence(compiled)
            fingerprint = _production_fingerprint(compiled, stack)
            if fingerprint != frozen["fingerprint"] or fingerprint != planned["fingerprint"]:
                raise BrollTaskError("compiled request differs from the frozen AutoDL plan")
            if evidence["compiled_workflow_sha256"] != frozen["compiled_workflow_sha256"]:
                raise BrollTaskError("compiled workflow changed after offline preparation")
            items.append(
                {
                    **dict(frozen),
                    "request_path_absolute": request_path,
                    "request": request,
                    "compiled": compiled,
                }
            )
        if not items:
            if legacy_unsubmitted:
                raise BrollTaskError(
                    "legacy AutoDL task has no recoverable prompt_id; migrate and reapprove its unsubmitted items"
                )
            raise BrollTaskError("live-run manifest contains no items")
        if legacy_unsubmitted:
            task = dict(task)
            task["_legacy_unsubmitted_items"] = legacy_unsubmitted
        committed = Decimal(str(task["budget"]["committed"]))
        hard_limit = Decimal(str(task["budget"]["hard_limit"]))
        spent = Decimal(str(task["budget"]["spent"]))
        if committed <= 0 or spent + committed > hard_limit:
            raise BrollTaskError("task budget does not cover the frozen live run")
        return task, items

    def _run_item(
        self,
        task_id: str,
        task: dict[str, Any],
        item: dict[str, Any],
        info: Any,
        *,
        poll_interval: float,
        timeout: float,
    ) -> dict[str, Any]:
        output, prompt_id = self._generate_item(
            task_id,
            item,
            info,
            poll_interval=poll_interval,
            timeout=timeout,
        )
        return self._download_item(
            task_id,
            task,
            item,
            info,
            output=output,
            prompt_id=prompt_id,
        )

    def _generate_item(
        self,
        task_id: str,
        item: dict[str, Any],
        info: Any,
        *,
        poll_interval: float,
        timeout: float,
    ) -> tuple[dict[str, str], str]:
        directory = self.tasks.directory(task_id)
        attempt_dir = Path(item["request_path_absolute"]).parent
        record_path = (
            directory / "provider" / self.PROVIDER_KEY / f"{item['fingerprint']}.json"
        )
        record = _read_json(record_path)
        prompt_id = str(record.get("prompt_id", "")).strip() if record else ""
        task_id_path = attempt_dir / "task-id.txt"
        task_file_prompt_id = (
            task_id_path.read_text(encoding="utf-8").strip()
            if task_id_path.is_file()
            else ""
        )
        if prompt_id and task_file_prompt_id and prompt_id != task_file_prompt_id:
            raise AutoDLProductionError(
                "provider record and task-id.txt disagree; stop instead of querying or resubmitting"
            )
        if (
            record
            and prompt_id
            and str(record.get("instance_id", "")).strip()
            and str(record.get("instance_id")) != str(info.instance_id)
        ):
            raise AutoDLProductionError(
                "saved prompt_id belongs to another AutoDL instance; connect to the original instance"
            )
        if not prompt_id and task_file_prompt_id:
            prompt_id = task_file_prompt_id
            if prompt_id:
                recovered = {
                    "schema_version": "autodl-direct-v1",
                    "task_id": task_id,
                    "shot_id": item["shot_id"],
                    "attempt": item["attempt"],
                    "fingerprint": item["fingerprint"],
                    "instance_id": info.instance_id,
                    "state": "recovered_from_task_id",
                    "prompt_id": prompt_id,
                    "recovered_at": now(),
                }
                if record is None:
                    try:
                        _write_json_exclusive(record_path, recovered)
                        record = recovered
                    except FileExistsError:
                        record = _read_json(record_path)
                else:
                    record.update(recovered)
                    _write_json(record_path, record)
        if record and not prompt_id:
            raise AutoDLProductionError(
                "submission outcome is unresolved; preserve the record and do not resubmit"
            )
        if not prompt_id:
            try:
                validate_h3_upload_gate(item["request"], item["compiled"])
            except H3InputError as exc:
                raise AutoDLProductionError(
                    f"H3 prompt hard gate rejected the request before upload: {exc}"
                ) from exc
            client_id = str(uuid5(NAMESPACE_URL, f"autodl-client:{info.instance_id}"))
            correlation_id = str(
                uuid5(NAMESPACE_URL, f"autodl-submit:{item['fingerprint']}")
            )
            record = {
                "schema_version": "autodl-direct-v1",
                "task_id": task_id,
                "shot_id": item["shot_id"],
                "attempt": item["attempt"],
                "fingerprint": item["fingerprint"],
                "instance_id": info.instance_id,
                "instance_context": _instance_lock_context(info, self.client),
                "state": "submitting",
                "prompt_id": None,
                "client_id": client_id,
                "correlation_id": correlation_id,
                "uploaded_names": [],
                "submitted_at": now(),
                **(
                    {"replacement_lineage": dict(item["replacement_lineage"])}
                    if isinstance(item.get("replacement_lineage"), Mapping)
                    else {}
                ),
            }
            try:
                _write_json_exclusive(record_path, record)
            except FileExistsError as exc:
                prior = _read_json(record_path) or {}
                raise AutoDLProductionError(
                    "request is already reserved "
                    f"({prior.get('prompt_id') or prior.get('state')}); recover it instead of resubmitting"
                ) from exc
            uploaded = tuple(
                self.client.upload_file(info, binding.local_path, binding.remote_name)
                for binding in item["compiled"].uploads
            )
            prompt = _bind_uploaded_names(item["compiled"], uploaded)
            record["uploaded_names"] = list(uploaded)
            _write_json(record_path, record)
            try:
                prompt_id = self.client.submit_prompt(
                    info,
                    prompt,
                    client_id=client_id,
                    correlation_id=correlation_id,
                )
            except BaseException as exc:
                record.update({"state": "ambiguous", "error": type(exc).__name__})
                _write_json(record_path, record)
                raise AutoDLProductionError(
                    "prompt submission is ambiguous; do not submit again"
                ) from exc
            record.update({"state": "submitted", "prompt_id": prompt_id, "error": None})
            _write_json(record_path, record)
        _write_text(task_id_path, prompt_id + "\n")
        saved_output = record.get("output") if isinstance(record, Mapping) else None
        if record.get("status") == "succeeded" and isinstance(saved_output, Mapping):
            status, output, error = "succeeded", dict(saved_output), None
        else:
            status, output, error = self._wait_prompt(
                info,
                prompt_id,
                record_path,
                poll_interval=poll_interval,
                timeout=timeout,
            )
        if status != "succeeded" or output is None:
            raise AutoDLProductionError(error or f"prompt {prompt_id} failed")
        return dict(output), prompt_id

    def _download_item(
        self,
        task_id: str,
        task: dict[str, Any],
        item: dict[str, Any],
        info: Any,
        *,
        output: dict[str, str],
        prompt_id: str,
    ) -> dict[str, Any]:
        attempt_dir = Path(item["request_path_absolute"]).parent
        result_path = attempt_dir / "result.json"
        if result_path.is_file():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            local_output = Path(str(result.get("download_path", "")))
            if local_output.is_file() and local_output.stat().st_size:
                digest = _sha256_file(local_output)
                recorded = str(result.get("output_sha256", "")).strip()
                if recorded and recorded != digest:
                    raise AutoDLProductionError(
                        f"downloaded output changed after receipt: {local_output}"
                    )
                if not recorded:
                    result["output_sha256"] = digest
                    _write_json(result_path, result)
                return result
        destination = (
            self.project_root
            / "outputs"
            / "generated"
            / task_id
            / f"{item['shot_id']}-{item['attempt']}.mp4"
        )
        if hasattr(self.client, "download_output_to"):
            self.client.download_output_to(info, output, destination)
        else:
            response = self.client.download_output(info, output)
            _write_bytes(destination, response.body)
        media_info = _basic_media_info(destination)
        target = (
            FOUR_K_DIMENSIONS[task["spec"]["ratio"]]
            if task["spec"]["resolution"] == "4K"
            else None
        )
        if target is not None:
            _require_video_dimensions(media_info, target)
        receipt = {
            "shot_id": item["shot_id"],
            "attempt": item["attempt"],
            "request_path": str(
                Path(item["request_path_absolute"]).relative_to(
                    self.tasks.directory(task_id)
                )
            ),
            "prompt_id": prompt_id,
            "fingerprint": item["fingerprint"],
            "provider_status": "succeeded",
            "download_path": str(destination),
            "output_sha256": _sha256_file(destination),
            "downloaded": True,
            "non_zero_size": destination.stat().st_size > 0,
            "basic_media_info": media_info,
            "target_dimensions": list(target) if target else None,
            "obvious_damage": False,
            "human_review": "pending",
            "actual_cost_status": "pending_platform_bill",
            "received_at": now(),
            **(
                {"replacement_lineage": dict(item["replacement_lineage"])}
                if isinstance(item.get("replacement_lineage"), Mapping)
                else {}
            ),
        }
        _write_json(result_path, receipt)
        return receipt

    def _wait_prompt(
        self,
        info: Any,
        prompt_id: str,
        record_path: Path,
        *,
        poll_interval: float,
        timeout: float,
    ) -> tuple[str, dict[str, str] | None, str | None]:
        if poll_interval < 10:
            raise ValueError("poll interval must be at least 10 seconds")
        deadline = time.monotonic() + timeout
        last_error: str | None = None
        while time.monotonic() < deadline:
            try:
                history = self.client.history(info, prompt_id)
                if history is not None:
                    status, output, error = _history_status(history)
                    if status in {"succeeded", "failed"}:
                        record = _read_json(record_path) or {}
                        record.update(
                            {
                                "state": "terminal",
                                "status": status,
                                "output": output,
                                "error": error,
                            }
                        )
                        _write_json(record_path, record)
                        return status, output, error
            except BaseException as exc:
                last_error = type(exc).__name__
            time.sleep(poll_interval)
        raise TimeoutError(
            f"prompt {prompt_id} is still recoverable after polling timeout"
            + (f" ({last_error})" if last_error else "")
        )

    def _deliver(self, task_id: str, results: list[dict[str, Any]]) -> None:
        final_dir = self.project_root / "outputs" / "final" / task_id
        final_dir.mkdir(parents=True, exist_ok=True)
        clips = []
        for result in results:
            source = Path(result["download_path"])
            target = final_dir / source.name
            shutil.copy2(source, target)
            clips.append(
                {
                    "shot_id": result["shot_id"],
                    "attempt": result["attempt"],
                    "prompt_id": result["prompt_id"],
                    "path": str(target),
                    "sha256": _sha256_file(target),
                    "source_sha256": str(result["output_sha256"]),
                    "request_path": str(result.get("request_path", "")),
                    "human_review": "pending",
                }
            )
        manifest = {
            "task_id": task_id,
            "delivered_at": now(),
            "delivery_status": "human_review_pending",
            "resolution": self.tasks.load(task_id)["spec"]["resolution"],
            "quality_policy": "quick_receipt_only",
            "local_super_resolution": False,
            "clips": clips,
        }
        runtime_overrides = self.tasks.load(task_id).get("runtime_overrides", {})
        if (
            isinstance(runtime_overrides, Mapping)
            and runtime_overrides.get("shutdown_after_success") is False
        ):
            manifest["authorized_handoff"] = runtime_overrides.get("authorized_handoff")
        _write_json(self.tasks.directory(task_id) / "delivery-manifest.json", manifest)
        task = self.tasks.load(task_id)
        task["delivery"].update(
            {"status": "human_review_pending", "human_review": "pending"}
        )
        self.tasks.save(task)
        self.tasks.write_status(
            task_id,
            "human_review_pending",
            f"{len(clips)} 条独立 B-roll 已下载；等待人工审片",
        )

    def shutdown(
        self, *, timeout: float = 180.0, poll_interval: float = 3.0
    ) -> dict[str, Any]:
        return dict(
            self.client.shutdown_and_wait(
                timeout=timeout, poll_interval=poll_interval
            )
        )

    def verify_stack(self) -> GoldenStackFingerprint:
        """Explicit migration/install audit; never called by ``run_batch``."""

        self.client.start()
        fingerprint = validate_golden_stack(
            self.client.system_stats(), self.golden_stack
        )
        runtime_fingerprint = validate_golden_runtime_evidence(
            self.client.runtime_receipt(), self.golden_stack
        )
        if runtime_fingerprint != fingerprint.golden_runtime_evidence_sha256:
            raise AutoDLProductionError("AutoDL stack receipts are inconsistent")
        return fingerprint

    def _record_shutdown(
        self, task_id: str, receipt: dict[str, Any], started_at: datetime
    ) -> None:
        stopped = _parse_time(receipt.get("verified_at"))
        if stopped is not None and stopped >= started_at:
            seconds = (stopped - started_at).total_seconds()
            receipt.update(
                {
                    "actual_cost_status": "pending_platform_bill",
                    "observed_seconds": round(seconds, 3),
                    "observed_cost_lower_bound_cny": str(
                        (
                            Decimal(str(seconds))
                            * self.pricing.hourly_rate_cny
                            / Decimal("3600")
                        ).quantize(Decimal("0.000001"))
                    ),
                }
            )
        directory = self.tasks.directory(task_id)
        _write_json(
            directory / "provider/autodl/receipts/shutdown-latest.json", receipt
        )
        task = self.tasks.load(task_id)
        task.setdefault("execution", {})["shutdown"] = receipt
        task["budget"]["actual_cost_status"] = "pending_platform_bill"
        self.tasks.save(task)
        manifest_path = directory / "delivery-manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["shutdown_receipt"] = receipt
            manifest["shutdown_verified"] = bool(receipt.get("shutdown_verified"))
            _write_json(manifest_path, manifest)

    def _completed_results(self, task_id: str) -> list[dict[str, Any]] | None:
        directory = self.tasks.directory(task_id)
        manifest_path = directory / "delivery-manifest.json"
        if not manifest_path.is_file():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        clips = manifest.get("clips")
        if (
            manifest.get("task_id") != task_id
            or not isinstance(clips, list)
            or not clips
            or not (
                manifest.get("shutdown_verified") is True
                or isinstance(manifest.get("authorized_handoff"), Mapping)
            )
        ):
            return None
        results: list[dict[str, Any]] = []
        for clip in clips:
            if not isinstance(clip, Mapping):
                return None
            shot_id = str(clip.get("shot_id", ""))
            attempt = str(clip.get("attempt", ""))
            request_path_value = str(clip.get("request_path", "")).strip()
            if request_path_value:
                request_path = _inside(directory, directory / request_path_value)
                result_path = request_path.parent / "result.json"
            else:
                result_path = directory / "h3-requests" / shot_id / attempt / "result.json"
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            generated = Path(str(result.get("download_path", "")))
            delivered = Path(str(clip.get("path", "")))
            if (
                result.get("provider_status") != "succeeded"
                or not generated.is_file()
                or not delivered.is_file()
                or _sha256_file(generated) != result.get("output_sha256")
                or _sha256_file(delivered) != clip.get("sha256")
                or clip.get("source_sha256") != result.get("output_sha256")
            ):
                return None
            results.append(result)
        return results

    def _approved_stack(self) -> GoldenStackFingerprint:
        return GoldenStackFingerprint(
            self.golden_stack.fingerprint_version,
            self.golden_stack.expected_fingerprint,
            self.golden_stack.golden_runtime_evidence_fingerprint,
            self.golden_stack.comfyui_version,
            self.golden_stack.required_frontend_version,
            self.golden_stack.gpu_name,
            self.golden_stack.minimum_vram_bytes,
        )

    def _load_existing_plan(self, task_id: str) -> dict[str, Any]:
        path = self.tasks.directory(task_id) / "generation-plan.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BrollTaskError("existing AutoDL generation plan is missing") from exc


def _production_fingerprint(compiled: Any, stack: GoldenStackFingerprint) -> str:
    base = str(compiled_workflow_evidence(compiled)["execution_fingerprint"])
    return _canonical_sha256(
        {
            "scheme": "autodl-compiled-workflow-golden-stack-v2",
            "compiled_execution_fingerprint": base,
            "golden_stack_fingerprint": stack.fingerprint_sha256,
            "golden_runtime_evidence_sha256": stack.golden_runtime_evidence_sha256,
            "golden_stack_version": stack.fingerprint_version,
        }
    )


def _offline_rtx_canary(compiled: Any) -> dict[str, Any]:
    from .canary import offline_rtx_frame_canary

    return dict(offline_rtx_frame_canary(compiled))


def _bind_uploaded_names(compiled: Any, uploaded: tuple[str, ...]) -> dict[str, Any]:
    if len(uploaded) != len(compiled.uploads):
        raise AutoDLProductionError(
            "uploaded input count differs from compiled workflow"
        )
    prompt = json.loads(json.dumps(compiled.prompt))
    mapping = {
        binding.remote_name: actual
        for binding, actual in zip(compiled.uploads, uploaded)
    }
    loader_inputs = {"LoadImage": "image", "LoadVideo": "file", "LoadAudio": "audio"}
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        input_name = loader_inputs.get(str(node.get("class_type", "")))
        if input_name is None:
            continue
        name = str(node.get("inputs", {}).get(input_name, ""))
        if name not in mapping:
            raise AutoDLProductionError("workflow contains an unbound input")
        node["inputs"][input_name] = mapping[name]
    return prompt


def _history_status(
    history: Mapping[str, Any],
) -> tuple[str, dict[str, str] | None, str | None]:
    status = history.get("status") if isinstance(history.get("status"), Mapping) else {}
    text = str(status.get("status_str", "")).lower()
    messages = status.get("messages") if isinstance(status.get("messages"), list) else []
    errors = [
        item
        for item in messages
        if isinstance(item, list) and item and item[0] == "execution_error"
    ]
    if errors or text in {"error", "failed"}:
        return "failed", None, json.dumps(
            errors[-1] if errors else status, ensure_ascii=False
        )
    outputs = history.get("outputs") if isinstance(history.get("outputs"), Mapping) else {}
    descriptors = _collect_video_descriptors(outputs)
    if descriptors:
        return "succeeded", descriptors[0], None
    if status.get("completed") is True and text in {"success", "succeeded"}:
        return "failed", None, "Comfy completed without a video output"
    return "running", None, None


def _collect_video_descriptors(value: Any) -> list[dict[str, str]]:
    """Match the proven benchmark parser across custom SaveVideo output shapes."""

    suffixes = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
    found: list[dict[str, str]] = []
    if isinstance(value, Mapping):
        filename = value.get("filename")
        if isinstance(filename, str) and Path(filename).suffix.lower() in suffixes:
            found.append(
                {
                    "filename": filename,
                    "subfolder": str(value.get("subfolder", "")),
                    "type": str(value.get("type", "output")),
                }
            )
        for child in value.values():
            found.extend(_collect_video_descriptors(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_collect_video_descriptors(child))
    unique = {
        (item["filename"], item["subfolder"], item["type"]): item for item in found
    }
    return list(unique.values())


def _basic_media_info(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        raise BrollTaskError("downloaded video is missing or empty")
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BrollTaskError("ffprobe could not read the downloaded video") from exc
    if result.returncode != 0:
        raise BrollTaskError("downloaded video is unreadable")
    try:
        probe = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BrollTaskError("ffprobe returned invalid JSON") from exc
    return {"checked": True, "size_bytes": path.stat().st_size, "probe": probe}


def _require_video_dimensions(
    media_info: Mapping[str, Any], expected: tuple[int, int]
) -> None:
    streams = media_info.get("probe", {}).get("streams", [])
    videos = [item for item in streams if item.get("codec_type") == "video"]
    if not videos:
        raise BrollTaskError("downloaded file has no video stream")
    actual = (
        int(videos[0].get("width", 0)),
        int(videos[0].get("height", 0)),
    )
    if actual != expected:
        raise BrollTaskError(
            f"downloaded video dimensions {actual} do not match {expected}"
        )


def _logical_items(plan: Mapping[str, Any]) -> list[tuple[Any, ...]]:
    return [
        (
            item.get("shot_id"),
            item.get("attempt"),
            item.get("request_path"),
            item.get("fingerprint"),
            item.get("compiled_workflow_sha256"),
            item.get("estimated_cost_cny"),
        )
        for item in plan.get("items", [])
    ]


def _plan_change_is_authorized_replacement(
    prior: Mapping[str, Any], current: Mapping[str, Any]
) -> bool:
    """Allow only the narrow plan rebase created by replacement authorization."""

    old_items = {
        str(item.get("request_path", "")): item
        for item in prior.get("items", [])
        if isinstance(item, Mapping)
    }
    new_items = {
        str(item.get("request_path", "")): item
        for item in current.get("items", [])
        if isinstance(item, Mapping)
    }
    if not old_items or not new_items:
        return False
    shared = set(old_items) & set(new_items)
    if any(
        _logical_items({"items": [old_items[path]]})
        != _logical_items({"items": [new_items[path]]})
        for path in shared
    ):
        return False
    removed = set(old_items) - set(new_items)
    added = set(new_items) - set(old_items)
    if not removed or len(removed) != len(added):
        return False
    replaced_old_paths: set[str] = set()
    for path in added:
        lineage = new_items[path].get("replacement_lineage")
        if not isinstance(lineage, Mapping):
            return False
        old_attempt = lineage.get("old_attempt")
        if not isinstance(old_attempt, Mapping):
            return False
        old_path = str(old_attempt.get("request_path", ""))
        if old_path not in removed or old_path in replaced_old_paths:
            return False
        replaced_old_paths.add(old_path)
    return replaced_old_paths == removed


def _archive_plan_and_live_run(directory: Path, prior: Mapping[str, Any]) -> None:
    root = directory / "generation-plans"
    root.mkdir(parents=True, exist_ok=True)
    numbers: list[int] = []
    for path in root.glob("plan-*.json"):
        try:
            numbers.append(int(path.stem.split("-")[-1]))
        except ValueError:
            continue
    number = max(numbers, default=0) + 1
    _write_json(root / f"plan-{number:03d}.json", prior)
    live_path = directory / "live-run.json"
    if live_path.is_file():
        try:
            live = json.loads(live_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BrollTaskError("existing live-run manifest is unreadable") from exc
        _write_json(root / f"live-run-{number:03d}.json", live)


def _inside(root: Path, candidate: Path) -> Path:
    resolved = candidate.expanduser().resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise BrollTaskError("task path escapes its directory")
    return resolved


def _normalize_instance_context(
    value: Mapping[str, Any], *, require_endpoint: bool = False
) -> dict[str, Any]:
    """Canonicalize the stable identity used for leases and replacement lineage."""

    provider_instance_id = str(value.get("provider_instance_id", "")).strip()
    endpoint_instance_uuid = str(value.get("endpoint_instance_uuid", "")).strip()
    ssh_host = str(value.get("ssh_host", "")).strip().lower()
    host_key_sha256 = str(value.get("host_key_sha256", "")).strip()
    try:
        ssh_port = int(value.get("ssh_port", 0))
    except (TypeError, ValueError) as exc:
        raise BrollTaskError("AutoDL instance context has an invalid SSH port") from exc
    if not provider_instance_id:
        raise BrollTaskError("AutoDL instance context requires a provider instance id")
    if require_endpoint and (
        not endpoint_instance_uuid
        or not ssh_host
        or not 1 <= ssh_port <= 65535
        or not host_key_sha256
    ):
        raise BrollTaskError(
            "replacement requires stable instance context plus SSH host, port, and host-key fingerprint"
        )
    return {
        "provider_instance_id": provider_instance_id,
        "endpoint_instance_uuid": endpoint_instance_uuid or provider_instance_id,
        "ssh_host": ssh_host or "unavailable",
        "ssh_port": ssh_port,
        "host_key_sha256": host_key_sha256 or "unavailable",
    }


def _replacement_authorization_path(directory: Path, authorization_id: str) -> Path:
    if not authorization_id.startswith("replacement-") or not all(
        character in "0123456789abcdef" for character in authorization_id.removeprefix("replacement-")
    ) or len(authorization_id) != len("replacement-") + 32:
        raise BrollTaskError("invalid replacement authorization id")
    return directory / "replacement-authorizations" / f"{authorization_id}.json"


def _replacement_authorizations(directory: Path) -> list[dict[str, Any]]:
    root = directory / "replacement-authorizations"
    if not root.is_dir():
        return []
    values: list[dict[str, Any]] = []
    for path in sorted(root.glob("replacement-*.json")):
        value = _read_json(path)
        if value is None:
            continue
        if value.get("schema_version") != "autodl-replacement-v1":
            raise BrollTaskError("replacement authorization has an unsupported schema")
        values.append(value)
    return values


def _attempt_name_is_valid(value: str) -> bool:
    return bool(re.fullmatch(r"attempt-[0-9]{3,}", value))


def _next_replacement_attempt_name(directory: Path, shot_id: str) -> str:
    if not shot_id or Path(shot_id).name != shot_id:
        raise BrollTaskError("replacement has an invalid shot id")
    attempts: list[int] = []
    for root in (directory / "h3-requests" / shot_id, directory / "h3-replacements" / shot_id):
        if not root.is_dir():
            continue
        for path in root.glob("attempt-*"):
            match = re.fullmatch(r"attempt-([0-9]{3,})", path.name)
            if match is not None:
                attempts.append(int(match.group(1)))
    return f"attempt-{max(attempts, default=0) + 1:03d}"


def _replacement_seed(old_fingerprint: str, authorization_id: str) -> int:
    if not re.fullmatch(r"[0-9a-f]{64}", old_fingerprint):
        raise BrollTaskError("replacement authorization has an invalid old request fingerprint")
    digest = hashlib.sha256(
        f"autodl-replacement-seed-v1:{old_fingerprint}:{authorization_id}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:7], "big")


def _instance_lock_context(info: Any, client: Any) -> dict[str, Any]:
    """Build a stable lock identity without treating a shared host key as an instance."""

    ssh_client = getattr(client, "ssh", None)
    endpoint = getattr(ssh_client, "endpoint", None)
    credentials = getattr(ssh_client, "credentials", None)
    return _normalize_instance_context(
        {
            "provider_instance_id": str(getattr(info, "instance_id", "")).strip(),
            "endpoint_instance_uuid": str(
                getattr(endpoint, "instance_uuid", getattr(info, "instance_id", ""))
            ).strip(),
            "ssh_host": str(getattr(endpoint, "host", "")).strip().lower(),
            "ssh_port": getattr(endpoint, "port", 0),
            "host_key_sha256": str(
                getattr(credentials, "ssh_host_key_sha256", "") or ""
            ).strip(),
        }
    )


def _validate_replacement_instance_context(
    items: list[Mapping[str, Any]], current_context: Mapping[str, Any]
) -> None:
    """Bind every replacement submission to the exact authorized target instance."""

    replacement_items = [
        item for item in items if isinstance(item.get("replacement_lineage"), Mapping)
    ]
    if not replacement_items:
        return
    normalized_current = _normalize_instance_context(
        current_context, require_endpoint=True
    )
    for item in replacement_items:
        lineage = item.get("replacement_lineage")
        assert isinstance(lineage, Mapping)
        expected = lineage.get("new_instance_context")
        if not isinstance(expected, Mapping) or _normalize_instance_context(
            expected, require_endpoint=True
        ) != normalized_current:
            raise AutoDLProductionError(
                "current AutoDL instance differs from the replacement-authorized target"
            )


@contextmanager
def _instance_submission_lease(
    root: Path, instance_context: Mapping[str, Any] | str, task_id: str
):
    """Allow only one local batch to own a concrete GPU instance at a time."""

    context = (
        _normalize_instance_context(instance_context)
        if isinstance(instance_context, Mapping)
        else {"legacy_instance_id": str(instance_context)}
    )
    lease_root = root / "work" / "autodl-instance-leases"
    lease_root.mkdir(parents=True, exist_ok=True)
    lease_key = _canonical_sha256(
        {"scheme": "autodl-instance-submission-lease-v2", "context": context}
    )
    lease_name = lease_key + ".lock"
    with (lease_root / lease_name).open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AutoDLProductionError(
                "this AutoDL instance is already owned by another local generation batch"
            ) from exc
        handle.seek(0)
        handle.truncate()
        json.dump(
            {
                "task_id": task_id,
                "instance_context": context,
                "lease_sha256": lease_key,
                "pid": os.getpid(),
                "acquired_at": now(),
            },
            handle,
            ensure_ascii=False,
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(value, dict):
        raise AutoDLProductionError(f"invalid provider record: {path}")
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def _write_json_exclusive(path: Path, payload: Any) -> None:
    """Create a durable reservation exactly once across concurrent processes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


__all__ = ["AutoDLProductionError", "BrollAutoDLService"]
