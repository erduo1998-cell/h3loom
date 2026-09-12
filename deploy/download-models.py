#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.parse


STACK_ROOT = pathlib.Path("/root/autodl-tmp/h3-stack")
COMFY_ROOT = STACK_ROOT / "ComfyUI"
DEFAULT_MANIFEST = STACK_ROOT / "incoming" / "model-manifest.json"
DATA_ROOT = pathlib.Path("/root/autodl-tmp")
ALLOWED_SUBDIRS = {"diffusion_models", "text_encoders", "vae", "loras"}
# Preserve enough persistent space for the Comfy environment, logs, uploaded
# fixtures and sixteen benchmark outputs after the last model lands.
POST_DOWNLOAD_RESERVE_BYTES = 40_000_000_000


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(16 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path: pathlib.Path, expected_bytes: int, expected_sha: str) -> bool:
    return (
        path.is_file()
        and path.stat().st_size == expected_bytes
        and sha256_file(path) == expected_sha
    )


def available_bytes(path: pathlib.Path) -> int:
    return int(os.statvfs(path).f_bavail) * int(os.statvfs(path).f_frsize)


def quarantine(path: pathlib.Path, label: str) -> pathlib.Path:
    stamp = f"{label}-{int(time.time())}"
    destination = path.with_name(path.name + f".{stamp}")
    counter = 1
    while destination.exists():
        destination = path.with_name(path.name + f".{stamp}-{counter}")
        counter += 1
    path.replace(destination)
    return destination


def validate_manifest(manifest: dict[str, object]) -> None:
    repo = str(manifest.get("repository") or "")
    revision = str(manifest.get("revision") or "")
    parsed = urllib.parse.urlparse(str(manifest.get("mirror_base_url") or ""))
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise SystemExit("invalid model repository")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise SystemExit("model revision must be a 40-character lowercase Git commit")
    if parsed.scheme != "https" or parsed.netloc != "hf-mirror.com" or parsed.path.rstrip("/"):
        raise SystemExit("model mirror must be exactly https://hf-mirror.com")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise SystemExit("model manifest has no files")
    seen_roles: set[str] = set()
    seen_targets: set[tuple[str, str]] = set()
    total = 0
    for item in files:
        if not isinstance(item, dict):
            raise SystemExit("invalid model item")
        role = str(item.get("role") or "")
        repository_path = str(item.get("repository_path") or "")
        subdir = str(item.get("comfy_subdir") or "")
        filename = pathlib.PurePosixPath(repository_path).name
        if not role or role in seen_roles:
            raise SystemExit(f"duplicate or empty model role: {role!r}")
        if (
            not repository_path
            or repository_path.startswith("/")
            or "\\" in repository_path
            or ".." in pathlib.PurePosixPath(repository_path).parts
            or filename in {"", ".", ".."}
        ):
            raise SystemExit(f"unsafe repository path: {repository_path!r}")
        if subdir not in ALLOWED_SUBDIRS:
            raise SystemExit(f"unsupported Comfy model directory: {subdir!r}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256") or "")):
            raise SystemExit(f"invalid SHA-256 for {role}")
        try:
            byte_count = int(item.get("bytes"))
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"invalid byte count for {role}") from exc
        if byte_count <= 0:
            raise SystemExit(f"non-positive byte count for {role}")
        target_key = (subdir, filename)
        if target_key in seen_targets:
            raise SystemExit(f"duplicate model target: {subdir}/{filename}")
        seen_roles.add(role)
        seen_targets.add(target_key)
        total += byte_count
    declared_total = manifest.get("total_bytes")
    if declared_total is not None and int(declared_total) != total:
        raise SystemExit("model manifest total_bytes does not match files")


def download(part: pathlib.Path, url: str) -> None:
    command = [
        "curl",
        "--fail",
        "--location",
        "--retry",
        "20",
        "--retry-all-errors",
        "--retry-delay",
        "5",
        "--connect-timeout",
        "30",
        "--speed-time",
        "120",
        "--speed-limit",
        "1024",
    ]
    if part.exists():
        command.extend(["--continue-at", "-"])
    command.extend(["--output", os.fspath(part), url])
    subprocess.run(command, check=True)


def verified_receipt_bytes(manifest: dict[str, object]) -> bytes:
    """Portable model identity; timestamps and machine paths are not identity."""
    value = {
        "schema_version": "2.0",
        "repository": manifest["repository"],
        "revision": manifest["revision"],
        "files": sorted([
            {key: item[key] for key in ("role", "repository_path", "comfy_subdir", "bytes", "sha256")}
            for item in manifest["files"]
        ], key=lambda item: item["role"]),
        "total_bytes": sum(int(item["bytes"]) for item in manifest["files"]),
    }
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def main() -> int:
    manifest_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    if not DATA_ROOT.is_dir() or not COMFY_ROOT.is_dir():
        raise SystemExit("persistent data root or installed ComfyUI directory is missing")
    if os.path.ismount(DATA_ROOT) is False:
        raise SystemExit(f"{DATA_ROOT} is not a mount point")
    receipt_root = STACK_ROOT / "receipts"
    receipt_root.mkdir(parents=True, exist_ok=True)
    verified_path = receipt_root / "models-verified.json"
    # A failed new verification must not leave an earlier success marker active.
    verified_path.unlink(missing_ok=True)
    repo = manifest["repository"]
    revision = manifest["revision"]
    base = manifest["mirror_base_url"].rstrip("/")
    receipts: list[dict[str, object]] = []

    forbidden = set(manifest.get("forbidden", []))
    for item in manifest["files"]:
        repository_path = item["repository_path"]
        filename = pathlib.PurePosixPath(repository_path).name
        if filename in forbidden:
            raise SystemExit(f"forbidden model requested: {filename}")

        target_dir = COMFY_ROOT / "models" / item["comfy_subdir"]
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / filename
        part = target.with_suffix(target.suffix + ".part")
        expected_bytes = int(item["bytes"])
        expected_sha = item["sha256"]
        started = time.time()
        if not verify(target, expected_bytes, expected_sha):
            if available_bytes(DATA_ROOT) < expected_bytes + POST_DOWNLOAD_RESERVE_BYTES:
                raise SystemExit(
                    f"insufficient persistent disk reserve before {filename}: "
                    f"need at least {expected_bytes + POST_DOWNLOAD_RESERVE_BYTES} bytes free"
                )
            if target.exists():
                quarantine(target, "invalid")
            url = f"{base}/{repo}/resolve/{revision}/{repository_path}?download=true"
            download(part, url)
            if not verify(part, expected_bytes, expected_sha):
                # A resumed file can be structurally wrong even though curl
                # exits successfully.  Preserve it for diagnosis and retry one
                # clean, byte-zero transfer; never silently accept a mismatch.
                if part.exists():
                    quarantine(part, "invalid")
                download(part, url)
            if not verify(part, expected_bytes, expected_sha):
                raise SystemExit(f"model verification failed after clean retry: {part}")
            part.replace(target)

        receipts.append(
            {
                "role": item["role"],
                "path": os.fspath(target),
                "bytes": target.stat().st_size,
                "sha256": expected_sha,
                "source_revision": revision,
                "elapsed_seconds": round(time.time() - started, 3),
            }
        )
        print(json.dumps(receipts[-1], ensure_ascii=False), flush=True)

    receipt_root = STACK_ROOT / "receipts"
    receipt_root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    receipt = {
        "schema_version": "1.0",
        "recorded_at": stamp,
        "repository": repo,
        "revision": revision,
        "files": receipts,
        "total_bytes": sum(int(entry["bytes"]) for entry in receipts),
    }
    (receipt_root / f"models-{stamp}.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary = verified_path.with_suffix(".json.part")
    temporary.write_bytes(verified_receipt_bytes(manifest))
    temporary.replace(verified_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
