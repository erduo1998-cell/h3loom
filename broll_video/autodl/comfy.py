"""Loopback-only ComfyUI adapter for an AutoDL instance.

The adapter intentionally has the same small *duck interface* used by the
existing H3 runtime.  It never accepts an externally supplied Comfy URL: the
only HTTP origin is a short-lived SSH forward to remote ``127.0.0.1:8188``.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import mimetypes
from pathlib import Path
from typing import Any, Iterator, Mapping
from urllib.parse import urlencode
import uuid
import time

from broll_video.h3.transport import HTTPResponse, Transport, UrllibTransport
from .control import AutoDLControlClient, IndeterminatePowerRequest, STOPPED_STATES
from .ssh import AutoDLSSHClient, AutoDLSSHError


class AutoDLComfyError(RuntimeError):
    """Raised when the fixed remote Comfy stack cannot be started or read."""


@dataclass(frozen=True)
class InstanceInfo:
    """Minimal running-instance description used by the local Comfy adapter."""

    instance_id: str
    status: str
    web_url: str
    price_per_hour_cny: float
    retain_price_per_hour_cny: float


class AutoDLComfyClient:
    """Control-plane backed Comfy client scoped to one tunnel session."""

    def __init__(
        self,
        ssh: AutoDLSSHClient,
        control: AutoDLControlClient | None = None,
        *,
        transport: Transport | None = None,
        price_per_hour_cny: float = 5.98,
    ) -> None:
        self.ssh = ssh
        self.control = control
        self.transport = transport or UrllibTransport()
        self.price_per_hour_cny = price_per_hour_cny
        self._base_url: str | None = None

    @contextmanager
    def session(self) -> Iterator["AutoDLComfyClient"]:
        """Hold a command-lifecycle SSH forward; nested sessions are harmless."""

        if self._base_url is not None:
            yield self
            return
        with self.ssh.tunnel_to_comfy() as base_url:
            self._base_url = base_url.rstrip("/")
            try:
                yield self
            finally:
                self._base_url = None

    def _url(self, path: str) -> str:
        if self._base_url is None or not self._base_url.startswith("http://127.0.0.1:"):
            raise AutoDLComfyError("AutoDL Comfy operation requires an active loopback SSH tunnel")
        return self._base_url + path

    def instance(self, *, timeout: float = 30.0) -> InstanceInfo:
        del timeout
        if self.control is None:
            status = "running"
            instance_uuid = self.ssh.endpoint.instance_uuid
        else:
            current = self.control.status()
            status = current.status.casefold()
            instance_uuid = current.instance_uuid
        return InstanceInfo(
            instance_id=instance_uuid,
            status=status,
            web_url=self._base_url or "",
            price_per_hour_cny=self.price_per_hour_cny,
            retain_price_per_hour_cny=0.0,
        )

    def require_running(self) -> InstanceInfo:
        info = self.instance()
        if info.status in STOPPED_STATES or info.status != "running":
            raise AutoDLComfyError(f"AutoDL instance is not running (status={info.status})")
        self.system_stats(info)
        return info

    def start(self) -> None:
        # The migrated data disk preserves the script bytes but not its execute
        # bit. Invoke the approved script through bash instead of mutating the
        # golden image on every boot.
        result = self.ssh.run(
            [
                "/bin/bash",
                "/root/autodl-tmp/h3-stack/incoming/launch-comfy.sh",
            ],
            timeout_seconds=300,
        )
        if "ready" not in result.stdout.casefold() and "already running" not in result.stdout.casefold():
            raise AutoDLComfyError("AutoDL Comfy launch did not report readiness")

    def runtime_receipt(self) -> Mapping[str, Any]:
        """Collect a small golden-image receipt without hashing model blobs.

        These checks read Git identities, package versions, the deterministic
        receipt produced by deploy/download-models.py, the small Comfy patch
        diff, and H3Keyframes SOURCE metadata. This does not rehash model blobs.
        """

        code = r'''import hashlib
import importlib.metadata
import json
import pathlib
import subprocess
import torch

root = pathlib.Path("/root/autodl-tmp/h3-stack")
comfy = root / "ComfyUI"

def git_head(path):
    return subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
    ).strip()

model_receipt = root / "receipts/models-verified.json"
patch = subprocess.check_output([
    "git", "-C", str(comfy), "diff", "--",
    "nodes.py", "comfy_extras/nodes_audio.py", "comfy_extras/nodes_video.py",
])
h3_source = json.loads(
    (comfy / "custom_nodes/h3-keyframes-only/SOURCE.json").read_text()
)
value = {
    "comfy_commit": git_head(comfy),
    "kj_nodes_commit": git_head(comfy / "custom_nodes/ComfyUI-KJNodes"),
    "rtx_nodes_commit": git_head(comfy / "custom_nodes/Nvidia_RTX_Nodes_ComfyUI"),
    "torch_version": torch.__version__,
    "sageattention_version": importlib.metadata.version("sageattention"),
    "model_receipt_sha256": hashlib.sha256(model_receipt.read_bytes()).hexdigest(),
    "recursive_patch_receipt_sha256": hashlib.sha256(patch).hexdigest(),
    "h3_keyframes_source_commit": str(h3_source["commit"]),
}
print(json.dumps(value, sort_keys=True))
'''
        try:
            result = self.ssh.run(
                ["/root/autodl-tmp/h3-stack/env/bin/python", "-c", code],
                timeout_seconds=45,
            )
            value = json.loads(result.stdout)
        except (AutoDLSSHError, OSError, json.JSONDecodeError) as exc:
            raise AutoDLComfyError("AutoDL golden runtime receipt is unavailable") from exc
        if not isinstance(value, Mapping):
            raise AutoDLComfyError("AutoDL golden runtime receipt is invalid")
        return value

    def system_stats(self, info: InstanceInfo | None = None, *, timeout: float = 30.0) -> Mapping[str, Any]:
        del info
        if self._base_url is not None:
            response = self.transport.request("GET", self._url("/system_stats"), timeout=timeout)
            return self._json(response, "ComfyUI system_stats")
        try:
            # The approved launch script already proves this exact curl path.
            # Keep routine readiness on the same implementation instead of
            # adding a second remote Python/urllib dependency.
            result = self.ssh.run(
                [
                    "/usr/bin/curl",
                    "--fail",
                    "--silent",
                    "--max-time",
                    "10",
                    "http://127.0.0.1:8188/system_stats",
                ],
                timeout_seconds=30,
            )
            value = json.loads(result.stdout)
        except (AutoDLSSHError, json.JSONDecodeError) as exc:
            raise AutoDLComfyError("AutoDL Comfy system_stats is unavailable") from exc
        if not isinstance(value, Mapping):
            raise AutoDLComfyError("AutoDL Comfy system_stats is invalid")
        return value

    def object_info(self, info: InstanceInfo, *, timeout: float = 60.0) -> Mapping[str, Any]:
        del info
        return self._json(self.transport.request("GET", self._url("/object_info"), timeout=timeout,
                                                max_response_bytes=64 * 1024 * 1024), "ComfyUI object_info")

    def upload_file(self, info: InstanceInfo, local_path: Path | str, remote_name: str, *, timeout: float = 120.0) -> str:
        del info
        source = Path(local_path).expanduser().resolve()
        remote = Path(remote_name)
        if not source.is_file() or not remote_name or remote_name.startswith(("/", "..")) or "\\" in remote_name or any(part in {"", ".", ".."} for part in remote.parts):
            raise AutoDLComfyError("unsafe or missing ComfyUI input file")
        boundary = "----broll-video-" + uuid.uuid4().hex
        subfolder = "" if str(remote.parent) == "." else remote.parent.as_posix()
        mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        body = bytearray()
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{remote.name}\"\r\nContent-Type: {mime}\r\n\r\n".encode())
        body.extend(source.read_bytes())
        for name, value in (("subfolder", subfolder), ("type", "input"), ("overwrite", "true")):
            body.extend(f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}".encode())
        body.extend(f"\r\n--{boundary}--\r\n".encode())
        value = self._json(self.transport.request("POST", self._url("/upload/image"), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, body=bytes(body), timeout=timeout), "ComfyUI upload")
        name = str(value.get("name") or remote.name).strip()
        returned_subfolder = str(value.get("subfolder") or subfolder).strip().strip("/")
        if not name:
            raise AutoDLComfyError("ComfyUI upload returned no input name")
        return f"{returned_subfolder}/{name}" if returned_subfolder else name

    upload_image = upload_file

    def submit_prompt(self, info: InstanceInfo, prompt: Mapping[str, Any], *, client_id: str | None = None, correlation_id: str | None = None, timeout: float = 60.0) -> str:
        del info
        body: dict[str, Any] = {"prompt": dict(prompt)}
        if client_id:
            body["client_id"] = client_id
        if correlation_id:
            body["extra_data"] = {"broll_correlation_id": correlation_id}
        value = self._json(self.transport.request("POST", self._url("/prompt"), json_body=body, timeout=timeout), "ComfyUI prompt submission")
        if isinstance(value.get("node_errors"), Mapping) and value["node_errors"]:
            raise AutoDLComfyError("ComfyUI rejected workflow nodes")
        prompt_id = str(value.get("prompt_id", "")).strip()
        if not prompt_id:
            raise AutoDLComfyError("ComfyUI prompt submission returned no prompt_id")
        return prompt_id

    def history(self, info: InstanceInfo, prompt_id: str, *, timeout: float = 30.0) -> Mapping[str, Any] | None:
        del info
        value = self._json(self.transport.request("GET", self._url(f"/history/{prompt_id}"), timeout=timeout), "ComfyUI history")
        result = value.get(prompt_id)
        return result if isinstance(result, Mapping) else None

    def queue(self, info: InstanceInfo, *, timeout: float = 30.0) -> Mapping[str, Any]:
        del info
        return self._json(self.transport.request("GET", self._url("/queue"), timeout=timeout), "ComfyUI queue")

    def download_output(self, info: InstanceInfo, output: Mapping[str, str], *, max_bytes: int = 512 * 1024 * 1024, timeout: float = 300.0) -> HTTPResponse:
        del info
        filename = str(output.get("filename", "")).strip()
        if not filename or Path(filename).name != filename or filename in {".", ".."}:
            raise AutoDLComfyError("invalid ComfyUI output filename")
        response = self.transport.request("GET", self._url("/view?") + urlencode({"filename": filename, "subfolder": str(output.get("subfolder", "")), "type": str(output.get("type", "output"))}), timeout=timeout, max_response_bytes=max_bytes)
        if not 200 <= response.status < 300:
            raise AutoDLComfyError("ComfyUI output download failed")
        content_type = {key.lower(): value for key, value in (response.headers or {}).items()}.get("content-type", "").split(";", 1)[0].lower()
        if not content_type.startswith("video/"):
            raise AutoDLComfyError("ComfyUI output is not a video content type")
        if response.url and response.url.split("?", 1)[0] != self._url("/view"):
            raise AutoDLComfyError("ComfyUI output download redirected unexpectedly")
        return response

    def download_output_to(
        self,
        info: InstanceInfo,
        output: Mapping[str, str],
        destination: Path | str,
        *,
        timeout: float = 900.0,
    ) -> Path:
        """Recover a durable output directly from the AutoDL data disk."""

        del info
        filename = str(output.get("filename", "")).strip()
        subfolder = str(output.get("subfolder", "")).strip().strip("/")
        output_type = str(output.get("type", "output")).strip()
        if (
            output_type != "output"
            or not filename
            or Path(filename).name != filename
            or any(part in {"", ".", ".."} for part in Path(subfolder).parts)
        ):
            raise AutoDLComfyError("invalid ComfyUI output path")
        relative = f"{subfolder}/{filename}" if subfolder else filename
        remote = f"/root/autodl-tmp/h3-stack/ComfyUI/output/{relative}"
        try:
            return self.ssh.copy_from(remote, destination, timeout_seconds=timeout)
        except AutoDLSSHError as exc:
            raise AutoDLComfyError("AutoDL output copy failed") from exc

    def shutdown_and_wait(self, *, timeout: float = 180.0, poll_interval: float = 3.0, **_: Any) -> dict[str, Any]:
        if self.control is None:
            return self._ssh_shutdown_and_wait(timeout=timeout, poll_interval=poll_interval)
        requested_at = datetime.now(timezone.utc).isoformat()
        uncertain = False
        try:
            request = self.control.power_off()
        except IndeterminatePowerRequest:
            request = None
            uncertain = True
        deadline = time.monotonic() + timeout
        last = request.status if request is not None else "unknown"
        polls = 0
        while time.monotonic() < deadline:
            current = self.control.status()
            last = current.status
            polls += 1
            if current.stopped:
                # Secondary evidence is deliberately after the control-plane
                # terminal proof. It cannot create a second power request.
                unreachable = False
                try:
                    with self.session():
                        self.system_stats()
                except (AutoDLComfyError, AutoDLSSHError, OSError):
                    unreachable = True
                return {
                    "instance_id": current.instance_uuid, "requested_at": requested_at,
                    "request_accepted": not uncertain,
                    "request_message": request.request_id if request is not None else None,
                    "shutdown_request_uncertain": uncertain,
                    "shutdown_verified": True, "shutdown_unverified": False,
                    "terminal_status": current.status, "last_status": last,
                    "verified_at": datetime.now(timezone.utc).isoformat(),
                    "poll_attempts": polls, "ssh_comfy_unreachable": unreachable,
                    "secondary_evidence": (
                        "ssh_unreachable" if unreachable else "ssh_still_reachable_after_control_stop"
                    ),
                    "error": None,
                }
            time.sleep(poll_interval)
        return {
            "instance_id": (
                request.instance_uuid
                if request is not None
                else self.control.credentials.instance_uuid
            ),
            "requested_at": requested_at,
            "request_accepted": not uncertain,
            "request_message": request.request_id if request is not None else None,
            "shutdown_request_uncertain": uncertain,
            "shutdown_verified": False, "shutdown_unverified": True, "terminal_status": None,
            "last_status": last, "verified_at": None, "poll_attempts": polls,
            "ssh_comfy_unreachable": None, "error": "terminal_control_state_not_observed",
        }

    def _ssh_shutdown_and_wait(
        self, *, timeout: float, poll_interval: float
    ) -> dict[str, Any]:
        """Use AutoDL's documented in-instance shutdown path for market instances."""

        requested_at = datetime.now(timezone.utc).isoformat()
        request_accepted = False
        try:
            self.ssh.run(
                [
                    "/bin/sh",
                    "-lc",
                    "nohup /usr/bin/shutdown >/tmp/broll-autodl-shutdown.log 2>&1 </dev/null &",
                ],
                timeout_seconds=30,
            )
            request_accepted = True
        except AutoDLSSHError:
            # The SSH connection may be cut by a successfully-started shutdown.
            pass
        deadline = time.monotonic() + timeout
        polls = 0
        while time.monotonic() < deadline:
            polls += 1
            try:
                self.ssh.run(["true"], timeout_seconds=15)
            except (AutoDLSSHError, OSError):
                return {
                    "instance_id": self.ssh.endpoint.instance_uuid,
                    "requested_at": requested_at,
                    "request_accepted": request_accepted,
                    "request_message": "/usr/bin/shutdown",
                    "shutdown_request_uncertain": not request_accepted,
                    "shutdown_verified": True,
                    "shutdown_unverified": False,
                    "terminal_status": "remote_os_shutdown_ssh_unreachable",
                    "last_status": "ssh_unreachable",
                    "verified_at": datetime.now(timezone.utc).isoformat(),
                    "poll_attempts": polls,
                    "ssh_comfy_unreachable": True,
                    "secondary_evidence": "ssh_unreachable_after_usr_bin_shutdown",
                    "verification_scope": "standard_autodl_market_instance_without_control_api",
                    "error": None,
                }
            time.sleep(poll_interval)
        return {
            "instance_id": self.ssh.endpoint.instance_uuid,
            "requested_at": requested_at,
            "request_accepted": request_accepted,
            "request_message": "/usr/bin/shutdown",
            "shutdown_request_uncertain": not request_accepted,
            "shutdown_verified": False,
            "shutdown_unverified": True,
            "terminal_status": None,
            "last_status": "ssh_still_reachable",
            "verified_at": None,
            "poll_attempts": polls,
            "ssh_comfy_unreachable": False,
            "verification_scope": "standard_autodl_market_instance_without_control_api",
            "error": "ssh_still_reachable_after_usr_bin_shutdown",
        }

    @staticmethod
    def _json(response: HTTPResponse, operation: str) -> Mapping[str, Any]:
        try:
            value = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AutoDLComfyError(f"{operation} returned invalid JSON") from exc
        if not 200 <= response.status < 300 or not isinstance(value, Mapping):
            raise AutoDLComfyError(f"{operation} failed")
        return value
