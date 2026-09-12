"""Approved AutoDL production CLI (also callable as ``python -m``)."""

from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
import sys

from broll_video.requests import load_request
from broll_video.task import BrollTaskStore

from .comfy import AutoDLComfyClient
from .control import (
    AutoDLControlClient,
    AutoDLControlPolicy,
    AutoDLSSHEndpoint,
)
from .credentials import AutoDLCredentials, write_secure_autodl_credentials
from .pricing import AutoDLPricingCatalog
from .readiness import GoldenStackFingerprint, GoldenStackPolicy
from .runtime import AutoDLRuntime
from .service import BrollAutoDLService
from .ssh import (
    AutoDLSSHClient,
    enroll_approved_host_key,
    parse_ssh_connection_command,
    scan_host_key_fingerprint,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="broll-autodl")
    parser.add_argument("--project-root", default=".")
    parser.add_argument(
        "--known-hosts",
        default="~/.config/broll-autodl/known_hosts",
        help="owner-only AutoDL SSH known_hosts file",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in (
        "credentials",
        "instance",
        "verify-stack",
    ):
        sub.add_parser(name)
    install = sub.add_parser("install-credentials")
    install.add_argument("--ssh-command")
    shutdown = sub.add_parser("shutdown")
    shutdown.add_argument("--timeout", type=float, default=180.0)
    dry = sub.add_parser("dry-run")
    dry.add_argument("--request", required=True)
    export = sub.add_parser("export-final-conditioning")
    export.add_argument("task_id")
    plan = sub.add_parser("plan-batch")
    plan.add_argument("task_id")
    authorize_replacement = sub.add_parser("authorize-replacement")
    authorize_replacement.add_argument("task_id")
    authorize_replacement.add_argument("--shot-id", required=True)
    authorize_replacement.add_argument("--attempt", required=True)
    authorize_replacement.add_argument("--reason", required=True)
    authorize_replacement.add_argument("--recovery-evidence", required=True)
    replace_attempt = sub.add_parser("replace-live-attempt")
    replace_attempt.add_argument("task_id")
    replace_attempt.add_argument("authorization_id")
    run = sub.add_parser("run-batch")
    run.add_argument("task_id")
    return parser


def _control(root: Path) -> tuple[AutoDLCredentials, AutoDLControlClient | None]:
    credentials = AutoDLCredentials.load(root)
    if credentials.connection_mode == "ssh":
        return credentials, None
    policy = AutoDLControlPolicy.load(root / "config/autodl-control.json")
    control = AutoDLControlClient(credentials, policy)
    return credentials, control


def _install_credentials(
    root: Path,
    known_hosts: str,
    *,
    ssh_command: str | None = None,
) -> dict[str, object]:
    """Install the SSH contract this instance has already proven in production."""

    if ssh_command is None:
        print("只需两步：1) 粘贴当次实例卡片上的 SSH 连接命令；2) 粘贴当次 SSH 密码。")
        ssh_command = input("1/2 SSH 连接命令: ").strip()
    else:
        print("SSH 连接命令已给定，只需粘贴当次实例卡片上的 SSH 密码。")
    ssh_password = getpass.getpass("SSH 密码（输入不会显示）: ").strip()
    ssh_user, ssh_host, ssh_port = parse_ssh_connection_command(ssh_command)
    policy = AutoDLControlPolicy.load(root / "config/autodl-control.json")
    if not any(
        ssh_host == suffix or ssh_host.endswith("." + suffix)
        for suffix in policy.allowed_ssh_host_suffixes
    ):
        raise RuntimeError("SSH 主机不属于项目批准的 AutoDL 域名")
    bootstrap_endpoint = AutoDLSSHEndpoint(ssh_host, ssh_port, "bootstrap")
    fingerprint = scan_host_key_fingerprint(bootstrap_endpoint)
    credentials = AutoDLCredentials._validated_ssh(
        ssh_user=ssh_user,
        ssh_password=ssh_password,
        ssh_host=ssh_host,
        ssh_port=ssh_port,
        ssh_host_key_sha256=fingerprint,
    )
    endpoint = AutoDLSSHEndpoint(ssh_host, ssh_port, credentials.instance_uuid)
    known_hosts_path = enroll_approved_host_key(
        endpoint,
        expected_fingerprint=fingerprint,
        known_hosts=_resolve(root, known_hosts),
    )
    credential_path = write_secure_autodl_credentials(root, credentials)
    return {
        "installed": str(credential_path),
        "known_hosts": str(known_hosts_path),
        "instance_uuid": credentials.instance_uuid,
        "connection_mode": "ssh",
        "ssh_connection_saved": True,
        "host_key_pinned": True,
    }


def _service(
    root: Path,
    known_hosts: str,
    credentials: AutoDLCredentials,
) -> BrollAutoDLService:
    pricing = AutoDLPricingCatalog.load(root / "config/autodl-pricing.json")
    if credentials.connection_mode != "ssh":
        raise RuntimeError("new AutoDL production requires the standard SSH instance")
    if credentials.ssh_host is None or credentials.ssh_port is None:
        raise RuntimeError("AutoDL SSH credentials have no endpoint")
    endpoint = AutoDLSSHEndpoint(
        credentials.ssh_host,
        credentials.ssh_port,
        credentials.instance_uuid,
    )
    comfy = AutoDLComfyClient(
        AutoDLSSHClient(endpoint, credentials, known_hosts=_resolve(root, known_hosts)),
        None,
        price_per_hour_cny=float(pricing.hourly_rate_cny),
    )
    return BrollAutoDLService(
        BrollTaskStore(root / "work/tasks"),
        pricing,
        comfy,
        project_root=root,
        golden_stack=GoldenStackPolicy.load(root / "config/autodl-stack-fingerprint.json"),
    )


def _offline_service(root: Path) -> BrollAutoDLService:
    pricing = AutoDLPricingCatalog.load(root / "config/autodl-pricing.json")
    return BrollAutoDLService(
        BrollTaskStore(root / "work/tasks"),
        pricing,
        object(),  # plan-batch never performs a provider I/O call
        project_root=root,
        golden_stack=GoldenStackPolicy.load(root / "config/autodl-stack-fingerprint.json"),
    )


def _resolve(root: Path, value: str) -> Path:
    target = Path(value).expanduser()
    return target.resolve() if target.is_absolute() else (root / target).resolve()


def _completed_results(root: Path, task_id: str) -> list[dict[str, object]] | None:
    """Return already-delivered receipts without loading credentials or powering a GPU."""

    service = BrollAutoDLService.__new__(BrollAutoDLService)
    service.tasks = BrollTaskStore(root / "work/tasks")
    return service._completed_results(task_id)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.project_root).expanduser().resolve()
    try:
        if args.command == "dry-run":
            policy = GoldenStackPolicy.load(root / "config/autodl-stack-fingerprint.json")
            stack = GoldenStackFingerprint(
                policy.fingerprint_version,
                policy.expected_fingerprint,
                policy.golden_runtime_evidence_fingerprint,
                policy.comfyui_version,
                policy.required_frontend_version,
                policy.gpu_name,
                policy.minimum_vram_bytes,
            )
            evidence = AutoDLRuntime().pre_submit_gate(
                load_request(args.request, expected_provider="autodl"),
                stack_fingerprint=stack,
            )
            payload = {
                "dry_run": True,
                "provider": "autodl-comfy-h3",
                "execution_fingerprint": evidence.execution_fingerprint,
                "golden_stack_fingerprint": evidence.stack_fingerprint.fingerprint_sha256,
                "golden_runtime_evidence_sha256": evidence.stack_fingerprint.golden_runtime_evidence_sha256,
                "profile": evidence.compiled.profile,
                "dimensions": [evidence.compiled.width, evidence.compiled.height],
                "frame_count": evidence.compiled.frame_count,
                "rtx_target_frame_count_canary": evidence.offline_rtx_frame_canary,
            }
        elif args.command == "plan-batch":
            payload = _offline_service(root).plan_batch(args.task_id)
        elif args.command == "export-final-conditioning":
            payload = _offline_service(root).export_final_conditioning(args.task_id)
        elif args.command == "authorize-replacement":
            payload = _offline_service(root).authorize_replacement(
                args.task_id,
                shot_id=args.shot_id,
                attempt=args.attempt,
                reason=args.reason,
                recovery_evidence=args.recovery_evidence,
            )
        elif args.command == "install-credentials":
            payload = _install_credentials(
                root,
                args.known_hosts,
                ssh_command=args.ssh_command,
            )
        elif args.command == "run-batch" and (
            existing := _completed_results(root, args.task_id)
        ) is not None:
            payload = existing
        else:
            credentials, client = _control(root)
            if args.command == "credentials":
                payload = {
                    "instance_uuid": credentials.instance_uuid,
                    "connection_mode": credentials.connection_mode,
                    "owner_only_credential": True,
                }
            elif args.command == "instance":
                if client is not None:
                    status = client.status()
                    endpoint = client.resolve_ssh_endpoint()
                    state = status.status
                else:
                    if credentials.ssh_host is None or credentials.ssh_port is None:
                        raise RuntimeError("AutoDL SSH credentials have no endpoint")
                    endpoint = AutoDLSSHEndpoint(
                        credentials.ssh_host,
                        credentials.ssh_port,
                        credentials.instance_uuid,
                    )
                    AutoDLSSHClient(
                        endpoint,
                        credentials,
                        known_hosts=_resolve(root, args.known_hosts),
                    ).run(["true"], timeout_seconds=30)
                    state = "running"
                payload = {
                    "instance_uuid": credentials.instance_uuid,
                    "status": state,
                    "connection_mode": credentials.connection_mode,
                    "ssh": {"host": endpoint.host, "port": endpoint.port},
                }
            else:
                if args.command == "run-batch":
                    service = _service(root, args.known_hosts, credentials)
                else:
                    service = _service(root, args.known_hosts, credentials)
                if args.command == "verify-stack":
                    evidence = service.verify_stack()
                    payload = {"stack_fingerprint": evidence.fingerprint_sha256, "full_verify": True}
                elif args.command == "run-batch":
                    payload = service.run_batch(
                        args.task_id,
                        shutdown_after=True,
                    )
                elif args.command == "replace-live-attempt":
                    payload = service.replace_live_attempt(
                        args.task_id,
                        args.authorization_id,
                        new_instance_context=service.current_instance_context(),
                    )
                else:
                    payload = service.shutdown(timeout=args.timeout)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
        return 0
    except Exception as exc:
        # Module errors never stringify credential objects, headers, argv, or
        # remote stderr.  Keep the public error surface intentionally small.
        print(json.dumps({"outcome": "error", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
