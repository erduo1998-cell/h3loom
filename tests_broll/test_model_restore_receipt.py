"""A fresh deployment must attest its own model receipt, without old disk state."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("model_download", ROOT / "deploy/download-models.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ModelRestoreReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.comfy = self.root / "ComfyUI"
        self.target = self.comfy / "models/vae/tiny.safetensors"
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"synthetic model fixture")
        self.manifest = {"repository": "test/model", "revision": "a" * 40,
                         "mirror_base_url": "https://hf-mirror.com", "files": [{
            "role": "test", "repository_path": "vae/tiny.safetensors", "comfy_subdir": "vae",
            "bytes": self.target.stat().st_size,
            "sha256": hashlib.sha256(self.target.read_bytes()).hexdigest()}]}
        self.path = self.root / "manifest.json"
        self.path.write_text(json.dumps(self.manifest))

    def run_download(self):
        with patch.object(module, "STACK_ROOT", self.root), patch.object(module, "DATA_ROOT", self.root), \
             patch.object(module, "COMFY_ROOT", self.comfy), patch.object(sys, "argv", ["download", str(self.path)]), \
             patch.object(module.os.path, "ismount", return_value=True), \
             patch.object(module, "available_bytes", return_value=0), \
             patch.object(module, "download", side_effect=AssertionError("network forbidden")), \
             contextlib.redirect_stdout(io.StringIO()):
            return module.main()

    def test_existing_valid_model_can_be_reverified_without_download_space(self):
        self.assertEqual(0, self.run_download())
        stable = self.root / "receipts/models-verified.json"
        first = stable.read_bytes()
        self.assertEqual(module.verified_receipt_bytes(self.manifest), first)
        self.assertNotIn(str(self.root).encode(), first)
        self.assertEqual(0, self.run_download())
        self.assertEqual(first, stable.read_bytes())

    def test_failed_reverification_invalidates_prior_success_marker(self):
        self.run_download()
        self.target.write_bytes(b"corrupt")
        with self.assertRaisesRegex(SystemExit, "insufficient persistent disk"):
            self.run_download()
        self.assertFalse((self.root / "receipts/models-verified.json").exists())

    def test_release_fingerprint_matches_deployer_model_identity(self):
        manifest = json.loads((ROOT / "deploy/model-manifest.json").read_text())
        policy = json.loads((ROOT / "config/autodl-stack-fingerprint.json").read_text())
        actual = hashlib.sha256(module.verified_receipt_bytes(manifest)).hexdigest()
        self.assertEqual(actual, policy["golden_runtime_evidence"]["model_receipt_sha256"])

    def test_model_order_and_license_metadata_do_not_change_identity(self):
        a = module.verified_receipt_bytes(self.manifest)
        self.manifest["license"] = {"reviewed_at": "later"}
        self.manifest["recorded_at"] = "later"
        self.assertEqual(a, module.verified_receipt_bytes(self.manifest))
