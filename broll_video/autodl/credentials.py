"""Owner-only AutoDL developer credentials.

The token is deliberately usable only by the AutoDL control client.  It is
never rendered by public receipts, sent through SSH, or stored in task state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Mapping


DEFAULT_SECURE_CONFIG = Path("secrets/autodl.local.json")


class AutoDLCredentialError(RuntimeError):
    """Raised when an AutoDL credential source is incomplete or unsafe."""


@dataclass(frozen=True)
class AutoDLCredentials:
    access_token: str | None = field(repr=False)
    instance_uuid: str
    ssh_user: str = "root"
    ssh_password: str | None = field(default=None, repr=False)
    ssh_host_key_sha256: str | None = None
    connection_mode: str = "control"
    ssh_host: str | None = None
    ssh_port: int | None = None

    @classmethod
    def load(
        cls,
        project_root: Path | str | None = None,
        *,
        environ: Mapping[str, str] | None = None,
        secure_config: Path | str | None = None,
    ) -> "AutoDLCredentials":
        """Load a complete env pair, otherwise a strict owner-only JSON file."""

        environment = os.environ if environ is None else environ
        token = str(environment.get("AUTODL_ACCESS_TOKEN", "")).strip()
        instance_uuid = str(environment.get("AUTODL_INSTANCE_UUID", "")).strip()
        if token or instance_uuid:
            if not token or not instance_uuid:
                raise AutoDLCredentialError(
                    "AUTODL_ACCESS_TOKEN and AUTODL_INSTANCE_UUID must be set together"
                )
            # Deliberately do not accept an SSH password from environment: process
            # environments are too easy to leak through diagnostics.  Key-based
            # SSH remains available in environment-only deployments.
            return cls._validated(
                token,
                instance_uuid,
                ssh_user=str(environment.get("AUTODL_SSH_USER", "root")),
                ssh_host_key_sha256=_optional_secret(
                    environment.get("AUTODL_SSH_HOST_KEY_SHA256")
                ),
            )

        root = Path(project_root or Path.cwd()).expanduser().resolve()
        target = Path(secure_config or root / DEFAULT_SECURE_CONFIG).expanduser().resolve()
        try:
            mode = stat.S_IMODE(target.stat().st_mode)
        except FileNotFoundError as exc:
            raise AutoDLCredentialError(
                f"AutoDL credential file does not exist: {target}"
            ) from exc
        if mode != 0o600:
            raise AutoDLCredentialError(
                f"AutoDL credential file must be exactly 0600, got {mode:04o}"
            )
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AutoDLCredentialError("AutoDL credential file is unreadable or invalid JSON") from exc
        if not isinstance(raw, Mapping):
            raise AutoDLCredentialError("AutoDL credential file must be a JSON object")
        if raw.get("connection_mode") == "ssh":
            return cls._validated_ssh(
                ssh_user=str(raw.get("ssh_user", "root")).strip(),
                ssh_password=_optional_secret(raw.get("ssh_password")),
                ssh_host=str(raw.get("ssh_host", "")).strip(),
                ssh_port=raw.get("ssh_port"),
                ssh_host_key_sha256=_optional_secret(raw.get("ssh_host_key_sha256")),
            )
        return cls._validated(
            str(raw.get("access_token", "")).strip(),
            str(raw.get("instance_uuid", "")).strip(),
            ssh_user=str(raw.get("ssh_user", "root")).strip(),
            ssh_password=_optional_secret(raw.get("ssh_password")),
            ssh_host_key_sha256=_optional_secret(raw.get("ssh_host_key_sha256")),
        )

    @staticmethod
    def _validated(
        token: str,
        instance_uuid: str,
        *,
        ssh_user: str = "root",
        ssh_password: str | None = None,
        ssh_host_key_sha256: str | None = None,
    ) -> "AutoDLCredentials":
        if len(token) < 8 or any(character.isspace() for character in token):
            raise AutoDLCredentialError("invalid AutoDL access token")
        if not instance_uuid or any(character.isspace() for character in instance_uuid):
            raise AutoDLCredentialError("invalid AutoDL instance UUID")
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", ssh_user):
            raise AutoDLCredentialError("invalid AutoDL SSH user")
        if ssh_password is not None and (not ssh_password or "\x00" in ssh_password):
            raise AutoDLCredentialError("invalid AutoDL SSH password")
        if ssh_host_key_sha256 is not None and not re.fullmatch(r"SHA256:[A-Za-z0-9+/=_-]+", ssh_host_key_sha256):
            raise AutoDLCredentialError("invalid AutoDL SSH host-key fingerprint")
        return AutoDLCredentials(token, instance_uuid, ssh_user, ssh_password, ssh_host_key_sha256)

    @staticmethod
    def _validated_ssh(
        *,
        ssh_user: str,
        ssh_password: str | None,
        ssh_host: str,
        ssh_port: object,
        ssh_host_key_sha256: str | None,
    ) -> "AutoDLCredentials":
        host = ssh_host.strip().lower().rstrip(".")
        if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", host):
            raise AutoDLCredentialError("invalid AutoDL SSH host")
        try:
            port = int(ssh_port)
        except (TypeError, ValueError) as exc:
            raise AutoDLCredentialError("invalid AutoDL SSH port") from exc
        if not 1 <= port <= 65535:
            raise AutoDLCredentialError("invalid AutoDL SSH port")
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", ssh_user):
            raise AutoDLCredentialError("invalid AutoDL SSH user")
        if not ssh_password or "\x00" in ssh_password:
            raise AutoDLCredentialError("AutoDL SSH password is required")
        if ssh_host_key_sha256 is None or not re.fullmatch(
            r"SHA256:[A-Za-z0-9+/=_-]+", ssh_host_key_sha256
        ):
            raise AutoDLCredentialError("invalid AutoDL SSH host-key fingerprint")
        stable_id = "ssh-" + hashlib.sha256(
            ssh_host_key_sha256.encode("utf-8")
        ).hexdigest()[:16]
        return AutoDLCredentials(
            None,
            stable_id,
            ssh_user,
            ssh_password,
            ssh_host_key_sha256,
            "ssh",
            host,
            port,
        )


def _optional_secret(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AutoDLCredentialError("AutoDL SSH credential fields must be strings")
    return value.strip()


def install_secure_autodl_credentials(
    project_root: Path | str,
    *,
    token_reader: object | None = None,
    instance_reader: object | None = None,
    host_key_reader: object | None = None,
) -> Path:
    """Interactively install the one-time owner-only AutoDL authority."""

    token_reader = getpass.getpass if token_reader is None else token_reader
    instance_reader = input if instance_reader is None else instance_reader
    host_key_reader = input if host_key_reader is None else host_key_reader
    if not all(callable(item) for item in (token_reader, instance_reader, host_key_reader)):
        raise TypeError("credential readers must be callable")
    token = str(token_reader("AutoDL developer token: ")).strip()
    instance_uuid = str(instance_reader("AutoDL Pro instance UUID: ")).strip()
    host_key = str(host_key_reader("Approved SSH host-key SHA256 fingerprint: ")).strip()
    config = AutoDLCredentials._validated(
        token,
        instance_uuid,
        ssh_host_key_sha256=host_key,
    )
    return write_secure_autodl_credentials(project_root, config)


def write_secure_autodl_credentials(
    project_root: Path | str,
    config: AutoDLCredentials,
) -> Path:
    """Persist already-discovered authority without ever rendering its token."""

    target = Path(project_root).expanduser().resolve() / DEFAULT_SECURE_CONFIG
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=target.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        os.chmod(temporary, 0o600)
        payload = (
            {
                "connection_mode": "ssh",
                "instance_uuid": config.instance_uuid,
                "ssh_user": config.ssh_user,
                "ssh_password": config.ssh_password,
                "ssh_host": config.ssh_host,
                "ssh_port": config.ssh_port,
                "ssh_host_key_sha256": config.ssh_host_key_sha256,
            }
            if config.connection_mode == "ssh"
            else {
                "connection_mode": "control",
                "access_token": config.access_token,
                "instance_uuid": config.instance_uuid,
                "ssh_user": config.ssh_user,
                "ssh_host_key_sha256": config.ssh_host_key_sha256,
            }
        )
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            indent=2,
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(target)
    os.chmod(target, 0o600)
    return target
