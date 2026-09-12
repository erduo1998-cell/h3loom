from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/audit_autodl_h3_stack.py"
SPEC = importlib.util.spec_from_file_location("audit_autodl_h3_stack", SCRIPT_PATH)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class H3StackPortabilityTest(unittest.TestCase):
    def test_production_model_manifest_is_internally_consistent(self) -> None:
        manifest = json.loads(
            (ROOT / "config/autodl-production-models.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(manifest["files"]), 8)
        self.assertEqual(
            manifest["total_bytes"], sum(item["bytes"] for item in manifest["files"])
        )
        production_paths = {item["repository_path"] for item in manifest["files"]}
        optional_paths = {
            item["repository_path"] for item in manifest["optional_compatibility_models"]
        }
        self.assertTrue(production_paths.isdisjoint(optional_paths))
        self.assertIn(
            "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
            optional_paths,
        )

    def test_exact_live_inventory_matches_the_production_manifest(self) -> None:
        manifest = json.loads(
            (ROOT / "config/autodl-production-models.json").read_text(encoding="utf-8")
        )
        golden = json.loads(
            (ROOT / "config/autodl-stack-fingerprint.json").read_text(encoding="utf-8")
        )
        evidence = golden["golden_runtime_evidence"]
        inventory = {
            "probe_mode": "read_only_full_model_hash",
            "system": {"gpu_available": False},
            "models": [
                {
                    "path": item["repository_path"],
                    "bytes": item["bytes"],
                    "sha256": item["sha256"],
                }
                for item in manifest["files"]
            ],
            "git_repositories": [
                {"path": "ComfyUI", "commit": evidence["comfy_commit"]},
                {
                    "path": "ComfyUI/custom_nodes/ComfyUI-KJNodes",
                    "commit": evidence["kj_nodes_commit"],
                },
                {
                    "path": "ComfyUI/custom_nodes/Nvidia_RTX_Nodes_ComfyUI",
                    "commit": evidence["rtx_nodes_commit"],
                },
            ],
            "h3_keyframes_source_commit": evidence["h3_keyframes_source_commit"],
        }
        comparison = AUDIT.compare_inventory(ROOT, inventory)
        self.assertTrue(comparison["matches_known_golden_stack"])
        self.assertTrue(comparison["model_hashes_checked"])
        self.assertEqual(comparison["live_expected_model_bytes"], manifest["total_bytes"])


if __name__ == "__main__":
    unittest.main()
