"""Strict SSH transport for the AutoDL loopback-only Comfy service.

Passwords, when an owner chooses password authentication, travel only through
an inherited pipe to ``sshpass -d``.  They are never rendered in an argv item,
environment variable, receipt, exception, or log.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import shlex
import socket
import subprocess
import tempfile
import time
from typing import Iterator, Sequence

from .control import AutoDLSSHEndpoint
from .credentials import AutoDLCredentials


class AutoDLSSHError(RuntimeError):
    """Raised for an unsafe SSH configuration or failed remote control command."""


def parse_ssh_connection_command(value: str) -> tuple[str, str, int]:
    """Turn the exact command copied from AutoDL into user, host and port."""

    normalized = value.replace("\u00a0", " ").replace("\\@", "@").strip()
    try:
        parts = shlex.split(normalized)
    except ValueError as exc:
        raise AutoDLSSHError("SSH 连接命令无法解析") from exc
    if not parts or parts[0] != "ssh":
        raise AutoDLSSHError("请粘贴 AutoDL 页面复制的完整 ssh 连接命令")
    port: int | None = None
    target: str | None = None
    index = 1
    while index < len(parts):
        item = parts[index]
        if item == "-p" and index + 1 < len(parts):
            try:
                port = int(parts[index + 1])
            except ValueError as exc:
                raise AutoDLSSHError("SSH 端口不是数字") from exc
            index += 2
            continue
        if item.startswith("-p") and len(item) > 2:
            try:
                port = int(item[2:])
            except ValueError as exc:
                raise AutoDLSSHError("SSH 端口不是数字") from exc
            index += 1
            continue
        if item.startswith("-") or target is not None:
            raise AutoDLSSHError("请只粘贴 AutoDL 页面给出的 ssh -p … root@… 命令")
        target = item
        index += 1
    if port is None or not 1 <= port <= 65535 or target is None or "@" not in target:
        raise AutoDLSSHError("SSH 连接命令缺少端口或 root@主机")
    user, host = target.rsplit("@", 1)
    host = host.strip().lower().rstrip(".")
    if not user or not host:
        raise AutoDLSSHError("SSH 连接命令缺少用户或主机")
    return user, host, port


def scan_host_key_fingerprint(endpoint: AutoDLSSHEndpoint) -> str:
    """Scan one API-attested endpoint and return its preferred SHA256 key."""

    scan = subprocess.run(
        ["ssh-keyscan", "-T", "10", "-p", str(endpoint.port), endpoint.host],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if scan.returncode not in {0, 1} or not scan.stdout.strip():
        raise AutoDLSSHError("AutoDL SSH 主机没有返回可用密钥")
    preferred = {"ssh-ed25519": 0, "ecdsa-sha2-nistp256": 1, "ssh-rsa": 2}
    candidates: list[tuple[int, str]] = []
    for line in scan.stdout.splitlines():
        fields = line.split(maxsplit=2)
        if len(fields) != 3 or fields[1] not in preferred:
            continue
        result = subprocess.run(
            ["ssh-keygen", "-lf", "-", "-E", "sha256"],
            input=line + "\n",
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            continue
        fingerprint = next(
            (part for part in result.stdout.split() if part.startswith("SHA256:")), None
        )
        if fingerprint:
            candidates.append((preferred[fields[1]], fingerprint))
    if not candidates:
        raise AutoDLSSHError("AutoDL SSH 主机密钥无法转换为 SHA256 指纹")
    return min(candidates)[1]


class AutoDLSSHClient:
    def __init__(
        self,
        endpoint: AutoDLSSHEndpoint,
        credentials: AutoDLCredentials,
        *,
        known_hosts: Path | str,
    ) -> None:
        self.endpoint = endpoint
        self.credentials = credentials
        self.known_hosts = Path(known_hosts).expanduser().resolve()
        if not self.known_hosts.is_file():
            raise AutoDLSSHError("AutoDL known_hosts file is missing")
        if not credentials.ssh_host_key_sha256:
            raise AutoDLSSHError("AutoDL SSH host-key fingerprint is required")

    def _ssh_command(self, remote: Sequence[str], *, tunnel: tuple[int, int] | None = None) -> list[str]:
        alias = _host_key_alias(self.endpoint)
        command = [
            "ssh", "-p", str(self.endpoint.port),
            "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={self.known_hosts}",
            "-o", f"HostKeyAlias={alias}",
            "-o", "ConnectTimeout=10", "-o", "ConnectionAttempts=1",
        ]
        # BatchMode suppresses password prompts.  Keep it for key-only use, but
        # never combine it with sshpass's inherited-fd password mode.
        if self.credentials.ssh_password is None:
            command.extend(["-o", "BatchMode=yes"])
        else:
            command.extend(["-o", "PreferredAuthentications=password,keyboard-interactive"])
        if tunnel is not None:
            local_port, remote_port = tunnel
            command.extend(["-N", "-L", f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}"])
        command.append(f"{self.credentials.ssh_user}@{self.endpoint.host}")
        # OpenSSH joins everything after the host and executes it through the
        # remote login shell.  Passing raw argv items would therefore let
        # spaces/semicolons inside Python ``-c`` snippets be reinterpreted by
        # that shell.  Send one safely quoted remote command string instead.
        if remote:
            command.append(shlex.join(remote))
        return command

    def _validate_host_key(self) -> None:
        alias = _host_key_alias(self.endpoint)
        lookup = subprocess.run(
            ["ssh-keygen", "-F", alias, "-f", str(self.known_hosts), "-l"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if lookup.returncode != 0 or self.credentials.ssh_host_key_sha256 not in lookup.stdout:
            raise AutoDLSSHError("approved AutoDL SSH host key is absent from known_hosts")

    def run(self, remote: Sequence[str], *, timeout_seconds: float = 60.0) -> subprocess.CompletedProcess[str]:
        """Run fixed argument-vector remote commands after local host-key proof."""

        self._validate_host_key()
        return self._run_command(self._ssh_command(remote), timeout_seconds=timeout_seconds)

    def copy_from(
        self,
        remote_path: str,
        local_path: Path | str,
        *,
        timeout_seconds: float = 900.0,
    ) -> Path:
        """Stream one fixed absolute remote file through pinned SSH.

        Comfy's ``/view`` endpoint can stop responding after a large video has
        been produced. The output itself is already durable on the AutoDL data
        disk, so production recovery copies that exact file without consulting
        Comfy history or submitting another prompt.
        """

        allowed_root = "/root/autodl-tmp/h3-stack/ComfyUI/output/"
        if (
            not remote_path.startswith(allowed_root)
            or ".." in Path(remote_path).parts
            or any(character in remote_path for character in "\r\n\x00")
        ):
            raise AutoDLSSHError("unsafe AutoDL output path")
        self._validate_host_key()
        destination = Path(local_path).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        alias = _host_key_alias(self.endpoint)
        command = [
            "scp", "-P", str(self.endpoint.port),
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={self.known_hosts}",
            "-o", f"HostKeyAlias={alias}",
            "-o", "ConnectTimeout=10",
            "-o", "ConnectionAttempts=1",
        ]
        if self.credentials.ssh_password is None:
            command.extend(["-o", "BatchMode=yes"])
        else:
            command.extend(
                ["-o", "PreferredAuthentications=password,keyboard-interactive"]
            )
        command.extend(
            [
                f"{self.credentials.ssh_user}@{self.endpoint.host}:{remote_path}",
                str(destination),
            ]
        )
        result = self._run_command(command, timeout_seconds=timeout_seconds)
        if result.returncode != 0 or not destination.is_file() or not destination.stat().st_size:
            raise AutoDLSSHError("AutoDL output copy failed")
        return destination

    def _run_command(self, command: list[str], *, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
        if self.credentials.ssh_password is None:
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds, check=False)
        else:
            if shutil.which("sshpass") is None:
                raise AutoDLSSHError("sshpass is required for the configured password-based SSH credential")
            reader, writer = os.pipe()
            try:
                os.set_inheritable(reader, True)
                # Password length is bounded by credentials validation and is written
                # before process launch; sshpass sees it only on its private fd.
                os.write(writer, self.credentials.ssh_password.encode("utf-8"))
                os.close(writer)
                writer = -1
                result = subprocess.run(
                    ["sshpass", "-d", str(reader), *command],
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    check=False,
                    pass_fds=(reader,),
                )
            finally:
                if writer != -1:
                    os.close(writer)
                os.close(reader)
        if result.returncode != 0:
            raise AutoDLSSHError("AutoDL SSH command failed")
        return result

    @contextmanager
    def tunnel_to_comfy(self, *, timeout_seconds: float = 30.0) -> Iterator[str]:
        """Create a short-lived, key-pinned local tunnel to remote loopback 8188."""

        self._validate_host_key()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as finder:
            finder.bind(("127.0.0.1", 0))
            local_port = int(finder.getsockname()[1])
        command = self._ssh_command((), tunnel=(local_port, 8188))
        password_reader = None
        if self.credentials.ssh_password is not None:
            if shutil.which("sshpass") is None:
                raise AutoDLSSHError("sshpass is required for the configured password-based SSH credential")
            password_reader, password_writer = os.pipe()
            try:
                os.set_inheritable(password_reader, True)
                os.write(password_writer, self.credentials.ssh_password.encode("utf-8"))
            finally:
                os.close(password_writer)
            command = ["sshpass", "-d", str(password_reader), *command]
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                pass_fds=((password_reader,) if password_reader is not None else ()),
            )
        finally:
            if password_reader is not None:
                os.close(password_reader)
        deadline = time.monotonic() + timeout_seconds
        try:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AutoDLSSHError("AutoDL SSH tunnel exited before becoming ready")
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    probe.settimeout(0.25)
                    if probe.connect_ex(("127.0.0.1", local_port)) == 0:
                        yield f"http://127.0.0.1:{local_port}"
                        return
                time.sleep(0.1)
            raise AutoDLSSHError("AutoDL SSH tunnel did not become ready")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def enroll_approved_host_key(
    endpoint: AutoDLSSHEndpoint,
    *,
    expected_fingerprint: str,
    known_hosts: Path | str,
) -> Path:
    """Enroll only a scanned key matching the separately approved fingerprint."""

    if not expected_fingerprint.startswith("SHA256:"):
        raise AutoDLSSHError("an approved SHA256 host-key fingerprint is required")
    scan = subprocess.run(
        ["ssh-keyscan", "-T", "10", "-p", str(endpoint.port), endpoint.host],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if scan.returncode not in {0, 1} or not scan.stdout.strip():
        raise AutoDLSSHError("AutoDL SSH host-key scan returned no keys")
    alias = _host_key_alias(endpoint)
    approved: list[str] = []
    for line in scan.stdout.splitlines():
        if not line or line.startswith("#"):
            continue
        fingerprint = subprocess.run(
            ["ssh-keygen", "-lf", "-", "-E", "sha256"],
            input=line + "\n",
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if fingerprint.returncode == 0 and expected_fingerprint in fingerprint.stdout:
            fields = line.split(maxsplit=2)
            if len(fields) == 3:
                approved.append(f"{alias} {fields[1]} {fields[2]}")
    if not approved:
        raise AutoDLSSHError("scanned AutoDL SSH host key does not match the approved fingerprint")
    target = Path(known_hosts).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
    retained = [line for line in existing if not line.startswith(alias + " ")]
    merged = retained + list(dict.fromkeys(approved))
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=target.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        os.chmod(temporary, 0o600)
        handle.write("\n".join(merged) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(target)
    os.chmod(target, 0o600)
    return target


def _host_key_alias(endpoint: AutoDLSSHEndpoint) -> str:
    """Stable trust name for a fixed instance behind changing proxy host/ports."""

    safe_uuid = "".join(
        char if char.isalnum() or char in "_.-" else "-"
        for char in endpoint.instance_uuid
    ).strip("-.")
    if not safe_uuid:
        raise AutoDLSSHError("AutoDL instance UUID cannot form a host-key alias")
    return f"autodl-{safe_uuid}"
