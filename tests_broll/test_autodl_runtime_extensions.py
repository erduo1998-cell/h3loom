"""Regression coverage for read-only conditioning and replacement runtime state."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest

from broll_video.autodl.pricing import AutoDLPricingCatalog
from broll_video.autodl.readiness import GoldenStackPolicy
from broll_video.autodl.service import (
    AutoDLProductionError,
    BrollAutoDLService,
    _instance_submission_lease,
    _validate_replacement_instance_context,
)
from broll_video.gold_contract import compile_gold_requests
from broll_video.task import BrollTaskError
import tests_broll.test_gold_contract as gold_contract_tests


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AutoDLRuntimeExtensionsTest(unittest.TestCase):
    def _prepared_gold_service(self) -> tuple[unittest.TestCase, dict, BrollAutoDLService]:
        fixture = gold_contract_tests.GoldProductionContractTest("runTest")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        task = fixture._task()
        fixture._approve(task)
        compile_gold_requests(fixture.store, task["task_id"])
        service = BrollAutoDLService(
            fixture.store,
            AutoDLPricingCatalog.load(PROJECT_ROOT / "config/autodl-pricing.json"),
            object(),
            project_root=fixture.root,
            golden_stack=GoldenStackPolicy.load(
                PROJECT_ROOT / "config/autodl-stack-fingerprint.json"
            ),
        )
        service.plan_batch(task["task_id"])
        fixture.store.authorize_generation(task["task_id"])
        return fixture, task, service

    def test_export_is_final_compiled_conditioning_not_stage_two_script(self) -> None:
        fixture, task, service = self._prepared_gold_service()

        exported = service.export_final_conditioning(task["task_id"])

        self.assertTrue(exported["read_only"])
        self.assertEqual("final_h3_conditioning", exported["artifact_type"])
        self.assertEqual(2, len(exported["items"]))
        item = exported["items"][0]
        self.assertEqual(
            "frozen_stage_two_generation_script_not_final_conditioning",
            item["stage_two_generation_script"]["label"],
        )
        self.assertTrue(
            item["conditioning"].startswith(
                "How the reference pictures align with the target video"
            )
        )
        self.assertNotEqual(
            item["stage_two_generation_script"]["sha256"],
            item["final_conditioning_sha256"],
        )
        self.assertEqual(64, len(item["final_conditioning_sha256"]))
        self.assertEqual(64, len(exported["export_sha256"]))
        self.assertFalse(
            (fixture.store.directory(task["task_id"]) / "final-conditioning.json").exists()
        )

    def test_replacement_requires_lineage_and_creates_a_new_attempt(self) -> None:
        fixture, task, service = self._prepared_gold_service()
        directory = fixture.store.directory(task["task_id"])
        original = next(
            item
            for item in service._approved_requests(task["task_id"])
            if item["shot_id"] == "b01" and item["attempt"] == "attempt-001"
        )
        old_record_path = directory / "provider/autodl" / f"{original['fingerprint']}.json"
        old_record_path.write_text(
            json.dumps(
                {
                    "schema_version": "autodl-direct-v1",
                    "task_id": task["task_id"],
                    "shot_id": "b01",
                    "attempt": "attempt-001",
                    "fingerprint": original["fingerprint"],
                    "instance_id": "old-instance",
                    "state": "submitted",
                    "prompt_id": "old-prompt-id",
                }
            ),
            encoding="utf-8",
        )
        live_original = {
            **original,
            "request_path_absolute": Path(original["request_path"]),
        }
        with self.assertRaisesRegex(AutoDLProductionError, "original instance"):
            service._generate_item(
                task["task_id"],
                live_original,
                type("Info", (), {"instance_id": "new-instance"})(),
                poll_interval=10,
                timeout=1,
            )

        authorization = service.authorize_replacement(
            task["task_id"],
            shot_id="b01",
            attempt="attempt-001",
            reason="原实例已释放，原 prompt 无法再查询或下载",
            recovery_evidence="用户确认实例已不可达且平台无法回收该 prompt",
        )
        with self.assertRaisesRegex(BrollTaskError, "must differ from the old instance"):
            service.replace_live_attempt(
                task["task_id"],
                authorization["authorization_id"],
                new_instance_context={
                    "provider_instance_id": "old-instance",
                    "endpoint_instance_uuid": "old-instance-uuid",
                    "ssh_host": "connect.westd.seetacloud.com",
                    "ssh_port": 33235,
                    "host_key_sha256": "SHA256:shared-host-key",
                },
            )
        replacement = service.replace_live_attempt(
            task["task_id"],
            authorization["authorization_id"],
            new_instance_context={
                "provider_instance_id": "new-instance",
                "endpoint_instance_uuid": "new-instance-uuid",
                "ssh_host": "connect.westd.seetacloud.com",
                "ssh_port": 33236,
                "host_key_sha256": "SHA256:shared-host-key",
            },
        )

        new_attempt = replacement["new_attempt"]
        self.assertEqual("live_attempt_created", replacement["state"])
        self.assertEqual("attempt-003", new_attempt["attempt"])
        self.assertEqual("old-prompt-id", new_attempt["replaces"]["prompt_id"])
        self.assertEqual("old-instance", new_attempt["replaces"]["instance_id"])
        self.assertEqual("new-instance", new_attempt["new_instance_context"]["provider_instance_id"])
        self.assertEqual("old-prompt-id", json.loads(old_record_path.read_text(encoding="utf-8"))["prompt_id"])

        original_payload = json.loads(Path(original["request_path"]).read_text(encoding="utf-8"))
        replacement_payload = json.loads(
            (directory / new_attempt["request_path"]).read_text(encoding="utf-8")
        )
        self.assertNotEqual(original_payload["seed"], replacement_payload["seed"])
        replacement_payload["seed"] = original_payload["seed"]
        self.assertEqual(original_payload, replacement_payload)

        replanned = service.plan_batch(task["task_id"])
        self.assertEqual(
            {"attempt-002", "attempt-003"},
            {item["attempt"] for item in replanned["items"]},
        )
        self.assertTrue(any("replacement_lineage" in item for item in replanned["items"]))

        class WrongInstanceClient:
            def __init__(self) -> None:
                self.started = False
                self.ssh = SimpleNamespace(
                    endpoint=SimpleNamespace(
                        instance_uuid="wrong-instance-uuid",
                        host="connect.westd.seetacloud.com",
                        port=33237,
                    ),
                    credentials=SimpleNamespace(
                        ssh_host_key_sha256="SHA256:shared-host-key"
                    ),
                )

            def start(self) -> None:
                self.started = True

            def instance(self) -> SimpleNamespace:
                return SimpleNamespace(instance_id="wrong-instance")

        wrong_client = WrongInstanceClient()
        service.client = wrong_client
        with self.assertRaisesRegex(
            AutoDLProductionError, "replacement-authorized target"
        ):
            service.run_batch(task["task_id"], shutdown_after=False)
        self.assertTrue(wrong_client.started)

        expected_context = new_attempt["new_instance_context"]
        replacement_items = [
            {
                "replacement_lineage": {
                    "new_instance_context": expected_context,
                }
            }
        ]
        _validate_replacement_instance_context(replacement_items, expected_context)
        with self.assertRaisesRegex(
            AutoDLProductionError, "replacement-authorized target"
        ):
            _validate_replacement_instance_context(
                replacement_items,
                {**expected_context, "ssh_port": 33237},
            )

    def test_accept_uses_delivery_request_path_for_replacement_result(self) -> None:
        fixture = gold_contract_tests.GoldProductionContractTest("runTest")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        task = fixture._task()
        directory = fixture.store.directory(task["task_id"])
        attempt_dir = directory / "h3-replacements/b01/attempt-003"
        attempt_dir.mkdir(parents=True)
        request_path = attempt_dir / "request.json"
        request_path.write_text("{}\n", encoding="utf-8")
        generated = directory / "generated-replacement.mp4"
        generated.write_bytes(b"replacement video bytes")
        digest = hashlib.sha256(generated.read_bytes()).hexdigest()
        (attempt_dir / "result.json").write_text(
            json.dumps(
                {
                    "shot_id": "b01",
                    "attempt": "attempt-003",
                    "provider_status": "succeeded",
                    "prompt_id": "replacement-prompt",
                    "fingerprint": "f" * 64,
                    "download_path": str(generated),
                    "output_sha256": digest,
                }
            ),
            encoding="utf-8",
        )
        (directory / "delivery-manifest.json").write_text(
            json.dumps(
                {
                    "task_id": task["task_id"],
                    "clips": [
                        {
                            "shot_id": "b01",
                            "attempt": "attempt-003",
                            "path": str(generated),
                            "sha256": digest,
                            "source_sha256": digest,
                            "request_path": str(request_path.relative_to(directory)),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        accepted = fixture.store.accept(task["task_id"])

        self.assertEqual("accepted", accepted["delivery"]["status"])
        result = json.loads((attempt_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual("accepted", result["human_review"])

    def test_shared_host_key_does_not_merge_distinct_instance_leases(self) -> None:
        fixture, _task, _service = self._prepared_gold_service()
        first = {
            "provider_instance_id": "ssh-shared-key",
            "endpoint_instance_uuid": "ssh-shared-key",
            "ssh_host": "connect.westd.seetacloud.com",
            "ssh_port": 33235,
            "host_key_sha256": "SHA256:shared-host-key",
        }
        second = {**first, "ssh_port": 33236}

        with _instance_submission_lease(fixture.root, first, "task-one"):
            with _instance_submission_lease(fixture.root, second, "task-two"):
                pass


if __name__ == "__main__":
    unittest.main()
