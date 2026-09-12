"""Offline release snapshot checks. No cloud access or credential reads."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def validate(root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    listed = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
    ).decode().split("\0")
    paths = sorted({p for p in listed if p})
    for rel in paths:
        path = root / rel
        if not path.is_file():
            failures.append(f"missing source: {rel}")
            continue
        if rel.split("/")[0] in {"work", "outputs", "secrets", "models", ".venv"}:
            failures.append(f"private directory in snapshot: {rel}")
        if path.suffix.lower() in {".whl", ".safetensors", ".ckpt", ".gguf", ".pem", ".key"}:
            failures.append(f"excluded artifact: {rel}")
        if path.suffix == ".md":
            body = path.read_text(encoding="utf-8")
            targets = re.findall(r"\]\(([^\s)]+)(?:\s+[^)]*)?\)", body)
            targets += re.findall(r'(?:src|href)="([^"]+)"', body)
            for target in targets:
                parsed = urlsplit(target.strip("<>"))
                if parsed.scheme or not parsed.path:
                    continue
                resolved = (path.parent / unquote(parsed.path)).resolve()
                if not resolved.is_relative_to(root) or not resolved.exists():
                    failures.append(f"broken local link: {rel} -> {target}")
        if path.name.endswith(".tar.gz"):
            with tarfile.open(path) as archive:
                for member in archive.getmembers():
                    parts = Path(member.name).parts
                    if member.name.startswith("/") or ".." in parts or any(
                        p == "__MACOSX" or p.startswith("._") for p in parts
                    ):
                        failures.append(f"unsafe/archive metadata entry: {rel}")
                    if member.issym() or member.islnk():
                        failures.append(f"archive link requires review: {rel}")

    for source in json.loads((root / "licenses/sources.json").read_text())["sources"]:
        actual = hashlib.sha256((root / source["file"]).read_bytes()).hexdigest()
        if actual != source["sha256"]:
            failures.append(f"license checksum mismatch: {source['file']}")

    a = json.loads((root / "config/autodl-production-models.json").read_text())
    b = json.loads((root / "deploy/model-manifest.json").read_text())
    if a != b:
        failures.append("production and deployment model manifests differ")
    pins = [x for x in (root / "deploy/cloud-requirements.txt").read_text().splitlines()
            if x and not x.startswith("#")]
    evidence = json.loads((root / "receipts/stack-inventory.json").read_text())["python"]["packages"]
    expected = ["nvidia-vfx==0.1.0.1" if x.startswith("nvidia-vfx @") else x for x in evidence]
    if sorted(pins) != sorted(expected):
        failures.append("cloud pins diverge from attested package receipt")
    if not all(re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9.+_-]+", p) for p in pins):
        failures.append("cloud requirements contain an unpinned or nonportable entry")
    return failures


if __name__ == "__main__":
    errors = validate()
    for error in errors:
        print(error, file=sys.stderr)
    print(f"Offline release checks: {'FAILED' if errors else 'PASS'}")
    raise SystemExit(bool(errors))
