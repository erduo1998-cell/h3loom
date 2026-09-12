from __future__ import annotations

import ast
import json
import unittest

from tests_broll.test_h3_stack_portability import AUDIT, ROOT


class AuditPrivacyTest(unittest.TestCase):
    def mount_summary(self, response):
        # Execute the actual remote helper locally with a synthetic findmnt response.
        tree = ast.parse(AUDIT.REMOTE_PROBE)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == "mount_summary")
        calls = []
        namespace = {"json": json, "command": lambda args: calls.append(args) or response}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "remote-helper", "exec"), namespace)
        result = namespace["mount_summary"]("/root/autodl-tmp/h3-stack")
        self.assertEqual(calls[0][calls[0].index("-o") + 1], "FSTYPE,TARGET")
        return result

    def test_mount_retains_layout_without_unique_device_id(self):
        result = self.mount_summary(json.dumps({"filesystems": [{
            "source": "/dev/md0[/volumes/synthetic-unique-device-123/_data]",
            "uuid": "synthetic-uuid-456", "fstype": "xfs", "target": "/root/autodl-tmp",
        }]}))
        self.assertEqual(result, {"fstype": "xfs", "target": "/root/autodl-tmp"})
        self.assertNotIn("synthetic", json.dumps(result))

    def test_missing_mount_is_not_invented(self):
        for response in (None, "invalid", '{"filesystems": []}'):
            with self.subTest(response=response):
                self.assertIsNone(self.mount_summary(response))

    def test_redacted_receipt_preserves_comparison_provenance(self):
        inventory = json.loads((ROOT / "receipts/stack-inventory.json").read_text())
        comparison = json.loads((ROOT / "receipts/golden-comparison.json").read_text())
        metadata = inventory["privacy_redaction"]
        self.assertTrue(metadata["is_redacted_copy"])
        self.assertEqual(metadata["original_inventory_sha256"], comparison["inventory_sha256"])
        self.assertEqual(set(inventory["system"]["mount"]), {"fstype", "target"})
        current = AUDIT.compare_inventory(ROOT, inventory)
        for key in comparison:
            if key != "inventory_sha256":
                self.assertEqual(current[key], comparison[key], key)
