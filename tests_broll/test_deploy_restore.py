"""Exercise only the installer's patch helper; never start a GPU or install packages.

Set H3_COMFY_FIXTURE_DIR to a checkout of the frozen upstream's three files for
the optional real-source check. Normal tests use small original patch contexts.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = (ROOT / "deploy/install-stack.sh").read_text()
HELPER = INSTALLER.split("die() {", 1)[1].split('\n[[ -d "$DATA_ROOT" ]]', 1)[0]
HELPER = "set -Eeuo pipefail\ndie() {" + HELPER
TARGETS = ("nodes.py", "comfy_extras/nodes_video.py", "comfy_extras/nodes_audio.py")


def original_contexts() -> dict[str, str]:
    result = {}
    for name in ("loadimage-recursive.patch", "loadmedia-recursive.patch"):
        patch = (ROOT / "deploy" / name).read_text()
        for section in patch.split("diff --git ")[1:]:
            lines = section.splitlines()
            target = lines[0].split(" b/", 1)[1]
            body = lines[next(i for i, line in enumerate(lines) if line.startswith("@@")) + 1:]
            result[target] = "".join(line[1:] + "\n" for line in body if line.startswith((" ", "-")))
    return result


class DeployRestoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        fixture_root = os.environ.get("H3_COMFY_FIXTURE_DIR")
        originals = original_contexts()
        for target in TARGETS:
            destination = self.repo / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(
                (Path(fixture_root) / target).read_bytes() if fixture_root else originals[target].encode()
            )
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
        self.commit = self.git("rev-parse", "HEAD").stdout.strip()

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True)

    def apply(self) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ, COMFY_ROOT=str(self.repo), COMFY_COMMIT=self.commit,
                           INCOMING_ROOT=str(ROOT / "deploy"))
        return subprocess.run(["bash", "-c", HELPER + "\napply_approved_comfy_patches\n"],
                              env=environment, capture_output=True, text=True)

    def snapshot(self) -> dict[str, bytes]:
        return {target: (self.repo / target).read_bytes() for target in TARGETS}

    def test_approved_patches_apply_once_and_preserve_index(self) -> None:
        original = self.snapshot()
        index = (self.repo / ".git/index").read_bytes()
        first = self.apply()
        self.assertEqual(first.returncode, 0, first.stderr)
        patched = self.snapshot()
        self.assertTrue(all(patched[name] != original[name] for name in TARGETS))
        second = self.apply()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(patched, self.snapshot())
        self.assertEqual(index, (self.repo / ".git/index").read_bytes())

    def test_unapproved_changes_fail_without_touching_files(self) -> None:
        self.assertEqual(self.apply().returncode, 0)
        with (self.repo / "nodes.py").open("a") as handle:
            handle.write("\n# unapproved change outside the patch hunk\n")
        before = self.snapshot()
        result = self.apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected ComfyUI changes", result.stderr)
        self.assertEqual(before, self.snapshot())

    def test_partial_media_patch_is_rejected(self) -> None:
        self.assertEqual(self.apply().returncode, 0)
        self.git("checkout", "HEAD", "--", "nodes.py", "comfy_extras/nodes_audio.py")
        before = self.snapshot()
        result = self.apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("partially applied ComfyUI patch", result.stderr)
        self.assertEqual(before, self.snapshot())

    def test_installed_sage_version_matches_golden_stack(self) -> None:
        fingerprint = json.loads((ROOT / "config/autodl-stack-fingerprint.json").read_text())
        expected = fingerprint["golden_runtime_evidence"]["sageattention_version"]
        requirements = (ROOT / "deploy/cloud-requirements.txt").read_text()
        self.assertIn('pip install -r "$INCOMING_ROOT/cloud-requirements.txt"', INSTALLER)
        self.assertEqual(re.findall(r"sageattention==([\d.]+)", requirements), [expected])


if __name__ == "__main__":
    unittest.main()
