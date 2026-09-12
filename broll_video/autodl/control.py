"""Small, fail-closed AutoDL Pro control-plane boundary.

It owns only instance discovery, status, power operations, and dynamic SSH
endpoint resolution from the authenticated snapshot.  It does not submit
ComfyUI prompts or store any task state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib import error, parse, request

from .credentials import AutoDLCredentials


API_BASE_URL = "https://api.autodl.com"
STOPPED_STATES = frozenset({"shutdown", "stopped", "off", "released"})
_HOST_RE = re.compile(r"(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$")


class AutoDLControlError(RuntimeError):
    """A definite control-plane or target-attestation failure."""


class IndeterminatePowerRequest(RuntimeError):
    """A power POST may have reached AutoDL and must not be retried automatically."""


@dataclass(frozen=True)
class AutoDLControlPolicy:
    gpu_spec_uuid: str
    snapshot_gpu_alias_name: str
    allowed_ssh_host_suffixes: tuple[str, ...]

    @classmethod
    def load(cls, path: Path | str) -> "AutoDLControlPolicy":
        try:
            payload = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AutoDLControlError("AutoDL control config is unreadable") from exc
        if not isinstance(payload, Mapping) or payload.get("provider") != "autodl":
            raise AutoDLControlError("AutoDL control config must identify provider=autodl")
        target = payload.get("power_on_attestation")
        if not isinstance(target, Mapping):
            raise AutoDLControlError("AutoDL control config lacks power_on_attestation")
        suffixes = target.get("allowed_ssh_host_suffixes")
        if not isinstance(suffixes, list) or not suffixes or not all(
            isinstance(item, str) and item and item == item.lower() and "." in item
            for item in suffixes
        ):
            raise AutoDLControlError("allowed_ssh_host_suffixes must be a non-empty hostname suffix array")
        spec = str(target.get("gpu_spec_uuid", "")).strip()
        alias = str(target.get("snapshot_gpu_alias_name", "")).strip()
        if not spec or not alias:
            raise AutoDLControlError("AutoDL power-on attestation is incomplete")
        return cls(spec, alias, tuple(suffixes))


@dataclass(frozen=True)
class AutoDLInstanceStatus:
    instance_uuid: str
    status: str
    request_id: str | None

    @property
    def stopped(self) -> bool:
        return self.status.casefold() in STOPPED_STATES


@dataclass(frozen=True)
class AutoDLSSHEndpoint:
    host: str
    port: int
    instance_uuid: str


@dataclass(frozen=True)
class AutoDLSSHAccess:
    """Ephemeral SSH access returned by the authenticated snapshot."""

    endpoint: AutoDLSSHEndpoint
    password: str | None = field(default=None, repr=False)
    payg_price_milli_cny: int = 0


HTTPCall = Callable[[str, str, Mapping[str, str], bytes | None, float], tuple[int, bytes]]


class _UrllibHTTP:
    def __call__(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float
    ) -> tuple[int, bytes]:
        outbound = request.Request(url, data=body, headers=dict(headers), method=method)
        try:
            with request.urlopen(outbound, timeout=timeout) as response:
                return response.status, response.read(1_000_000)
        except error.HTTPError as exc:
            return exc.code, exc.read(1_000_000)


class AutoDLControlClient:
    def __init__(
        self,
        credentials: AutoDLCredentials,
        policy: AutoDLControlPolicy,
        *,
        http: HTTPCall | None = None,
    ) -> None:
        if credentials.connection_mode != "control" or not credentials.access_token:
            raise AutoDLControlError("AutoDL control client requires developer-token credentials")
        self.credentials = credentials
        self.policy = policy
        self._http = http or _UrllibHTTP()

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": self.credentials.access_token, "Content-Type": "application/json"}

    def _call(
        self,
        method: str,
        endpoint: str,
        *,
        query: Mapping[str, str] | None = None,
        payload: Mapping[str, Any] | None = None,
        power_post: bool = False,
    ) -> Mapping[str, Any]:
        url = f"{API_BASE_URL}{endpoint}"
        if query:
            url += "?" + parse.urlencode(query)
        body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
        try:
            status, raw = self._http(method, url, self._headers, body, 30.0)
        except (OSError, TimeoutError) as exc:
            if power_post:
                raise IndeterminatePowerRequest("AutoDL power POST transport outcome is unknown") from exc
            raise AutoDLControlError(f"AutoDL transport failure during {method} {endpoint}") from exc
        try:
            response = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if power_post:
                raise IndeterminatePowerRequest("AutoDL power POST response is unreadable") from exc
            raise AutoDLControlError(f"AutoDL returned unreadable response ({status})") from exc
        if not isinstance(response, Mapping):
            raise AutoDLControlError("AutoDL response is not a JSON object")
        if not 200 <= status < 300 or response.get("code") != "Success":
            message = str(response.get("msg", ""))[:300]
            raise AutoDLControlError(f"AutoDL {method} {endpoint} failed: HTTP {status} {message}")
        return response

    def list_instances(self) -> tuple[Mapping[str, Any], ...]:
        """Return authenticated Pro rows for one-time local instance discovery."""

        response = self._call(
            "POST", "/api/v1/dev/instance/pro/list", payload={"page_index": 1, "page_size": 100}
        )
        data = response.get("data")
        rows = data.get("list") if isinstance(data, Mapping) else None
        if not isinstance(rows, list):
            raise AutoDLControlError("AutoDL list response has no instance list")
        if not all(isinstance(row, Mapping) for row in rows):
            raise AutoDLControlError("AutoDL list response contains an invalid instance row")
        return tuple(rows)

    def _list_instance(self) -> tuple[Mapping[str, Any], None]:
        rows = self.list_instances()
        selected = next(
            (
                row for row in rows
                if isinstance(row, Mapping) and row.get("uuid") == self.credentials.instance_uuid
            ),
            None,
        )
        if selected is None or selected.get("uuid") != self.credentials.instance_uuid:
            raise AutoDLControlError("configured instance UUID was not returned exactly by AutoDL")
        return selected, None

    def status(self) -> AutoDLInstanceStatus:
        response = self._call(
            "GET", "/api/v1/dev/instance/pro/status",
            query={"instance_uuid": self.credentials.instance_uuid},
        )
        value = response.get("data")
        if not isinstance(value, str) or not value.strip():
            raise AutoDLControlError("AutoDL status response data is not a non-empty string")
        return AutoDLInstanceStatus(
            instance_uuid=self.credentials.instance_uuid,
            status=value.strip(),
            request_id=_request_id(response),
        )

    def _snapshot(self) -> Mapping[str, Any]:
        response = self._call(
            "GET", "/api/v1/dev/instance/pro/snapshot",
            query={"instance_uuid": self.credentials.instance_uuid},
        )
        value = response.get("data")
        if not isinstance(value, Mapping):
            raise AutoDLControlError("AutoDL snapshot data is not an object")
        return value

    def resolve_ssh_endpoint(self) -> AutoDLSSHEndpoint:
        """Resolve the current endpoint from an authenticated snapshot, never config text."""

        snapshot = self._snapshot()
        return self.resolve_ssh_endpoint_from_snapshot(snapshot)

    def resolve_ssh_access(self) -> AutoDLSSHAccess:
        """Return current endpoint plus an ephemeral password when AutoDL supplies one."""

        snapshot = self._snapshot()
        endpoint = self.resolve_ssh_endpoint_from_snapshot(snapshot)
        raw_password = snapshot.get("root_password")
        password = raw_password if isinstance(raw_password, str) and raw_password else None
        if password is not None and "\x00" in password:
            raise AutoDLControlError("AutoDL snapshot returned an invalid SSH credential")
        return AutoDLSSHAccess(endpoint, password, self._live_payg_milli(snapshot))

    def power_on(self) -> AutoDLInstanceStatus:
        row, _ = self._list_instance()
        if row.get("gpu_spec_uuid") != self.policy.gpu_spec_uuid:
            raise AutoDLControlError("AutoDL list GPU spec differs from the approved target")
        snapshot = self._snapshot()
        if snapshot.get("snapshot_gpu_alias_name") != self.policy.snapshot_gpu_alias_name:
            raise AutoDLControlError("AutoDL snapshot GPU alias differs from the approved target")
        self._live_payg_milli(snapshot)
        self.resolve_ssh_endpoint_from_snapshot(snapshot)
        current = self.status()
        if current.status.casefold() == "running":
            return current
        response = self._call(
            "POST", "/api/v1/dev/instance/pro/power_on",
            payload={"instance_uuid": self.credentials.instance_uuid, "payload": "gpu"},
            power_post=True,
        )
        return AutoDLInstanceStatus(self.credentials.instance_uuid, current.status, _request_id(response))

    def power_off(self) -> AutoDLInstanceStatus:
        """Issue one caller-authorized POST; uncertain outcomes are never retried here."""

        try:
            current = self.status()
        except AutoDLControlError:
            current = None
        if current is not None and current.stopped:
            return current
        response = self._call(
            "POST", "/api/v1/dev/instance/pro/power_off",
            payload={"instance_uuid": self.credentials.instance_uuid},
            power_post=True,
        )
        return AutoDLInstanceStatus(
            self.credentials.instance_uuid,
            current.status if current is not None else "unknown",
            _request_id(response),
        )

    def resolve_ssh_endpoint_from_snapshot(self, snapshot: Mapping[str, Any]) -> AutoDLSSHEndpoint:
        """Internal helper that lets power-on reuse its one authenticated snapshot."""

        host = str(snapshot.get("proxy_host", "")).strip().lower().rstrip(".")
        raw_port = snapshot.get("ssh_port")
        if not _HOST_RE.fullmatch(host) or not any(
            host == suffix or host.endswith("." + suffix)
            for suffix in self.policy.allowed_ssh_host_suffixes
        ):
            raise AutoDLControlError("AutoDL snapshot returned an untrusted SSH host")
        if isinstance(raw_port, bool):
            raise AutoDLControlError("AutoDL snapshot returned an invalid SSH port")
        try:
            port = int(raw_port)
        except (TypeError, ValueError) as exc:
            raise AutoDLControlError("AutoDL snapshot returned an invalid SSH port") from exc
        if not 1 <= port <= 65535:
            raise AutoDLControlError("AutoDL snapshot returned an invalid SSH port")
        return AutoDLSSHEndpoint(host, port, self.credentials.instance_uuid)

    @staticmethod
    def _live_payg_milli(snapshot: Mapping[str, Any]) -> int:
        raw = snapshot.get("payg_price")
        if isinstance(raw, bool):
            raise AutoDLControlError("AutoDL snapshot returned an invalid payg price")
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise AutoDLControlError("AutoDL snapshot returned an invalid payg price") from exc
        if value <= 0:
            raise AutoDLControlError("AutoDL snapshot returned an invalid payg price")
        return value


def _request_id(response: Mapping[str, Any]) -> str | None:
    value = response.get("request_id")
    return value if isinstance(value, str) and value else None
