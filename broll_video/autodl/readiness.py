"""SSH-mediated loopback Comfy readiness and small golden-stack attestation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Mapping

from .control import AutoDLSSHEndpoint


class AutoDLReadinessError(RuntimeError):
    """Raised when SSH/Comfy evidence is unavailable or differs from the golden stack."""


@dataclass(frozen=True)
class GoldenStackPolicy:
    fingerprint_version: str
    comfyui_version: str
    required_frontend_version: str
    gpu_name: str
    minimum_vram_bytes: int
    expected_fingerprint: str
    golden_runtime_evidence: Mapping[str, str]
    golden_runtime_evidence_fingerprint: str

    @classmethod
    def load(cls, path: Path | str) -> "GoldenStackPolicy":
        try:
            payload = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AutoDLReadinessError("AutoDL golden stack config is unreadable") from exc
        if not isinstance(payload, Mapping) or payload.get("provider") != "autodl":
            raise AutoDLReadinessError("AutoDL golden stack config must identify provider=autodl")
        expected = payload.get("expected")
        if not isinstance(expected, Mapping):
            raise AutoDLReadinessError("AutoDL golden stack config lacks expected fields")
        try:
            policy = cls(
                fingerprint_version=str(payload["fingerprint_version"]),
                comfyui_version=str(expected["comfyui_version"]),
                required_frontend_version=str(expected["required_frontend_version"]),
                gpu_name=str(expected["gpu_name"]),
                minimum_vram_bytes=int(expected["minimum_vram_bytes"]),
                expected_fingerprint=str(payload["fingerprint_sha256"]),
                golden_runtime_evidence={str(key): str(value) for key, value in dict(payload["golden_runtime_evidence"]).items()},
                golden_runtime_evidence_fingerprint=str(payload["golden_runtime_evidence_sha256"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AutoDLReadinessError("AutoDL golden stack config is incomplete") from exc
        if (
            not policy.fingerprint_version
            or policy.minimum_vram_bytes <= 0
            or not re.fullmatch(r"[0-9a-f]{64}", policy.expected_fingerprint)
            or not re.fullmatch(r"[0-9a-f]{64}", policy.golden_runtime_evidence_fingerprint)
        ):
            raise AutoDLReadinessError("AutoDL golden stack fingerprint config is invalid")
        if policy.expected_fingerprint != _fingerprint_for(
            policy.comfyui_version, policy.required_frontend_version, policy.gpu_name
        ):
            raise AutoDLReadinessError("AutoDL golden stack fingerprint config is self-inconsistent")
        if policy.golden_runtime_evidence_fingerprint != _mapping_fingerprint(policy.golden_runtime_evidence):
            raise AutoDLReadinessError("AutoDL golden runtime evidence config is self-inconsistent")
        return policy


@dataclass(frozen=True)
class GoldenStackFingerprint:
    fingerprint_version: str
    fingerprint_sha256: str
    golden_runtime_evidence_sha256: str
    comfyui_version: str
    required_frontend_version: str
    gpu_name: str
    vram_total_bytes: int


SSHRunner = Callable[..., subprocess.CompletedProcess[str]]


def check_comfy_ready(
    endpoint: AutoDLSSHEndpoint,
    *,
    known_hosts: Path | str,
    runner: SSHRunner = subprocess.run,
    ssh_user: str = "root",
    timeout_seconds: float = 30.0,
) -> Mapping[str, Any]:
    """Read `/system_stats` through a key-pinned SSH hop to remote loopback only."""

    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", ssh_user):
        raise AutoDLReadinessError("invalid AutoDL SSH user")
    known = Path(known_hosts).expanduser()
    if not known.is_file():
        raise AutoDLReadinessError("AutoDL known_hosts file is missing")
    remote = (
        "import json,urllib.request;"
        "r=urllib.request.urlopen('http://127.0.0.1:8188/system_stats',timeout=10);"
        "print(json.dumps(json.load(r)))"
    )
    command = [
        "ssh", "-p", str(endpoint.port), "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={known}",
        "-o", f"HostKeyAlias=autodl-{endpoint.instance_uuid}",
        "-o", "ConnectTimeout=10", "-o", "ConnectionAttempts=1",
        f"{ssh_user}@{endpoint.host}", "python3", "-c", remote,
    ]
    try:
        result = runner(command, capture_output=True, text=True, timeout=timeout_seconds, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AutoDLReadinessError("AutoDL SSH/Comfy readiness probe did not complete") from exc
    if result.returncode != 0:
        raise AutoDLReadinessError("AutoDL SSH/Comfy readiness probe failed")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AutoDLReadinessError("AutoDL Comfy readiness probe returned invalid JSON") from exc
    if not isinstance(value, Mapping):
        raise AutoDLReadinessError("AutoDL Comfy system_stats is not an object")
    return value


def validate_golden_stack(
    system_stats: Mapping[str, Any], policy: GoldenStackPolicy
) -> GoldenStackFingerprint:
    """Validate a small runtime identity, not a routine multi-hundred-GB model hash."""

    system = system_stats.get("system")
    devices = system_stats.get("devices")
    if not isinstance(system, Mapping) or not isinstance(devices, list) or len(devices) != 1:
        raise AutoDLReadinessError("AutoDL system_stats does not describe exactly one GPU stack")
    device = devices[0]
    if not isinstance(device, Mapping):
        raise AutoDLReadinessError("AutoDL system_stats GPU entry is invalid")
    comfy_version = str(system.get("comfyui_version", ""))
    frontend_version = str(system.get("required_frontend_version", ""))
    raw_gpu_name = str(device.get("name", ""))
    gpu_name = _normalise_gpu_name(raw_gpu_name)
    try:
        vram = int(device.get("vram_total"))
    except (TypeError, ValueError) as exc:
        raise AutoDLReadinessError("AutoDL system_stats GPU VRAM is invalid") from exc
    fingerprint = _fingerprint_for(comfy_version, frontend_version, gpu_name)
    if fingerprint != policy.expected_fingerprint:
        raise AutoDLReadinessError("AutoDL golden stack fingerprint mismatch")
    if vram < policy.minimum_vram_bytes:
        raise AutoDLReadinessError("AutoDL golden stack VRAM is below the approved minimum")
    return GoldenStackFingerprint(
        fingerprint_version=policy.fingerprint_version,
        fingerprint_sha256=fingerprint,
        golden_runtime_evidence_sha256=policy.golden_runtime_evidence_fingerprint,
        comfyui_version=comfy_version,
        required_frontend_version=frontend_version,
        gpu_name=gpu_name,
        vram_total_bytes=vram,
    )


def validate_daily_readiness(
    system_stats: Mapping[str, Any], policy: GoldenStackPolicy
) -> GoldenStackFingerprint:
    """Cheap per-session check after the immutable image passed full verification once."""

    devices = system_stats.get("devices")
    if not isinstance(devices, list) or len(devices) != 1 or not isinstance(devices[0], Mapping):
        raise AutoDLReadinessError("AutoDL system_stats does not describe exactly one GPU")
    device = devices[0]
    gpu_name = _normalise_gpu_name(str(device.get("name", "")))
    try:
        vram = int(device.get("vram_total"))
    except (TypeError, ValueError) as exc:
        raise AutoDLReadinessError("AutoDL system_stats GPU VRAM is invalid") from exc
    if gpu_name != policy.gpu_name:
        raise AutoDLReadinessError("AutoDL daily readiness reached the wrong GPU")
    if vram < policy.minimum_vram_bytes:
        raise AutoDLReadinessError("AutoDL daily readiness VRAM is below the approved minimum")
    return GoldenStackFingerprint(
        fingerprint_version=policy.fingerprint_version,
        fingerprint_sha256=policy.expected_fingerprint,
        golden_runtime_evidence_sha256=policy.golden_runtime_evidence_fingerprint,
        comfyui_version=policy.comfyui_version,
        required_frontend_version=policy.required_frontend_version,
        gpu_name=gpu_name,
        vram_total_bytes=vram,
    )


def validate_golden_runtime_evidence(
    evidence: Mapping[str, object], policy: GoldenStackPolicy
) -> str:
    """Compare a small trusted remote receipt; never re-hash model blobs here."""

    actual = {key: str(evidence.get(key, "")) for key in policy.golden_runtime_evidence}
    if actual != dict(policy.golden_runtime_evidence):
        raise AutoDLReadinessError("AutoDL golden runtime evidence mismatch")
    return _mapping_fingerprint(actual)


def _normalise_gpu_name(value: str) -> str:
    text = re.sub(r"^cuda:\d+\s+", "", value.strip())
    return text.split(" : ", 1)[0]


def _fingerprint_for(comfyui_version: str, frontend_version: str, gpu_name: str) -> str:
    value = {
        "comfyui_version": comfyui_version,
        "gpu_name": gpu_name,
        "required_frontend_version": frontend_version,
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _mapping_fingerprint(value: Mapping[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
