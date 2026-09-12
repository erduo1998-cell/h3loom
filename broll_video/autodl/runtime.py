"""AutoDL production pre-submit gate for the approved golden image.

The golden image has already received its complete node-contract audit.  A new
AutoDL session therefore proves only its small runtime fingerprint and the
offline compiled-graph canary before it may submit normal fast/keyframe work.
It deliberately has no M5 experimental path and no M4 switch.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from broll_video.h3.models import H3Request
from broll_video.h3.prompt_gate import validate_h3_upload_gate
from .canary import offline_rtx_frame_canary
from .graph import CompiledWorkflow

from .readiness import GoldenStackFingerprint
from .workflow import (
    AutoDLWorkflowCompiler,
    compiled_workflow_evidence,
    final_conditioning_evidence,
)


class AutoDLRuntimeError(RuntimeError):
    pass


DEFAULT_PROFILES = frozenset({"fast", "precision_keyframes"})
FORBIDDEN_EXPERIMENTAL_PROFILES = frozenset({"refine_2pass_exp", "refine_2pass_int8_exp"})


@dataclass(frozen=True)
class AutoDLPreSubmitEvidence:
    compiled: CompiledWorkflow
    execution_fingerprint: str
    stack_fingerprint: GoldenStackFingerprint
    offline_rtx_frame_canary: dict[str, Any]
    environment_gate: str = "golden_stack_readiness_passed"


class AutoDLRuntime:
    """Compile and prove a normal production request without a live object_info audit."""

    def __init__(self, *, compiler: AutoDLWorkflowCompiler | None = None) -> None:
        self.compiler = compiler or AutoDLWorkflowCompiler()

    def pre_submit_gate(
        self,
        request: H3Request,
        *,
        stack_fingerprint: GoldenStackFingerprint,
        m4_enabled: bool = False,
    ) -> AutoDLPreSubmitEvidence:
        if m4_enabled:
            raise AutoDLRuntimeError("M4 is permanently forbidden for AutoDL production")
        if request.provider_profile in FORBIDDEN_EXPERIMENTAL_PROFILES:
            raise AutoDLRuntimeError("M5 experimental profiles are not part of the AutoDL default runtime")
        if request.provider_profile not in DEFAULT_PROFILES:
            raise AutoDLRuntimeError("AutoDL request provider profile is not approved")
        if not stack_fingerprint.fingerprint_sha256:
            raise AutoDLRuntimeError("AutoDL submission requires a current verified golden stack fingerprint")
        compiled = self.compiler.compile(request)
        validate_h3_upload_gate(request, compiled)
        canary = offline_rtx_frame_canary(compiled)
        if request.resolution == "4K" and not canary.get("passed"):
            raise AutoDLRuntimeError("AutoDL 4K request failed the offline RTX frame canary")
        evidence = compiled_workflow_evidence(compiled)
        return AutoDLPreSubmitEvidence(
            compiled=compiled,
            execution_fingerprint=str(evidence["execution_fingerprint"]),
            stack_fingerprint=stack_fingerprint,
            offline_rtx_frame_canary=canary,
        )

    def export_final_conditioning(self, request: H3Request) -> dict[str, str]:
        """Compile locally and expose the exact Comfy conditioning for review.

        This is intentionally read-only: it never opens an SSH tunnel, uploads
        media, starts Comfy, or submits a prompt.
        """

        compiled = self.compiler.compile(request)
        validate_h3_upload_gate(request, compiled)
        return final_conditioning_evidence(compiled)


class AutoDLPromptRuntime:
    """Small offline fingerprint helper retained for compatibility tests.

    Live prompt persistence and recovery belong exclusively to
    :class:`BrollAutoDLService`; this class performs no submission or polling.
    """

    def __init__(self, state_dir: Path | str, client: Any, *, stack_fingerprint: GoldenStackFingerprint) -> None:
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.client = client
        self.compiler = AutoDLWorkflowCompiler()
        self.stack_fingerprint = stack_fingerprint

    def production_fingerprint(self, compiled: CompiledWorkflow) -> str:
        """Bind the exact compiled graph to the approved AutoDL golden image."""

        base = str(compiled_workflow_evidence(compiled)["execution_fingerprint"])
        payload = {
            "scheme": "autodl-compiled-workflow-golden-stack-v2",
            "compiled_execution_fingerprint": base,
            "golden_stack_fingerprint": self.stack_fingerprint.fingerprint_sha256,
            "golden_runtime_evidence_sha256": self.stack_fingerprint.golden_runtime_evidence_sha256,
            "golden_stack_version": self.stack_fingerprint.fingerprint_version,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
