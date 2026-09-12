from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from broll_video.autodl.comfy import InstanceInfo
from broll_video.autodl.pricing import AutoDLPricingCatalog
from broll_video.autodl.readiness import GoldenStackPolicy
from broll_video.autodl.service import (
    AutoDLProductionError,
    BrollAutoDLService,
    _write_json_exclusive,
)
from broll_video.h3.models import H3InputError
from broll_video.h3.prompt_gate import SFX_ONLY_GUARD, validate_h3_motion_prompt
from broll_video.task import BrollTaskError, BrollTaskStore


ROOT = Path(__file__).resolve().parents[1]


class ThreeStageHardeningTest(unittest.TestCase):
    def _store_and_task(self, root: Path, *, gold: bool = False):
        source = root / "source.srt"
        source.write_text(
            "1\n00:00:00,000 --> 00:00:06,000\n测试。\n", encoding="utf-8"
        )
        store = BrollTaskStore(root / "work/tasks")
        task = store.create(
            name="hardening",
            source_srt=source,
            ratio="16:9",
            execution_mode="authorized",
            production_contract=None if not gold else "agent-know-gold-v1",
        )
        return store, task

    def test_prompt_gate_keeps_time_and_transitions_but_rejects_real_script_conflicts(self) -> None:
        prompt = (
            "图1至图3是这个6秒、16:9视频唯一的画面与风格标准。\n"
            "[Shot 1] 00:00.000–00:03.000 缓慢推进；"
            "[Shot 2] 00:03.000 match cut 后侧向跟拍。\n"
            "同步音效：轨道滑动与实体扣合声。"
            + SFX_ONLY_GUARD
        )
        self.assertEqual(
            prompt,
            validate_h3_motion_prompt(
                prompt,
                anchor_count=3,
                audio_policy="sfx_only",
                duration=6,
                ratio="16:9",
            ),
        )
        with self.assertRaisesRegex(H3InputError, "duration, ratio"):
            validate_h3_motion_prompt(
                prompt.replace("6秒、16:9", "15秒、9:16"),
                anchor_count=3,
                audio_policy="sfx_only",
                duration=6,
                ratio="16:9",
            )
        with self.assertRaisesRegex(H3InputError, "raw narration"):
            validate_h3_motion_prompt(
                prompt.replace("[Shot 1]", "source_quote：口播原文\n[Shot 1]"),
                anchor_count=3,
                audio_policy="sfx_only",
            )
        with self.assertRaisesRegex(H3InputError, "voice or music"):
            validate_h3_motion_prompt(
                prompt.replace("缓慢推进", "缓慢推进，同时背景音乐响起并有人对话"),
                anchor_count=3,
                audio_policy="sfx_only",
            )

    def test_provider_reservation_is_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "record.json"
            _write_json_exclusive(path, {"state": "reserved"})
            with self.assertRaises(FileExistsError):
                _write_json_exclusive(path, {"state": "second-submit"})

    def test_task_id_only_recovery_never_uploads_or_submits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store, task = self._store_and_task(root)
            directory = store.directory(task["task_id"])
            attempt = directory / "h3-requests/b01/attempt-001"
            attempt.mkdir(parents=True)
            (attempt / "task-id.txt").write_text("existing-prompt\n", encoding="utf-8")

            class RecoveryClient:
                def __init__(self) -> None:
                    self.calls: list[str] = []

                def upload_file(self, *_args):
                    self.calls.append("upload")
                    raise AssertionError("recovery must not upload")

                def submit_prompt(self, *_args, **_kwargs):
                    self.calls.append("submit")
                    raise AssertionError("recovery must not submit")

                def history(self, _info, prompt_id):
                    self.calls.append(f"history:{prompt_id}")
                    return {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {
                            "92": {
                                "files": [
                                    {
                                        "filename": "recovered.mp4",
                                        "subfolder": "",
                                        "type": "output",
                                    }
                                ]
                            }
                        },
                    }

            client = RecoveryClient()
            service = BrollAutoDLService(
                store,
                AutoDLPricingCatalog.load(ROOT / "config/autodl-pricing.json"),
                client,
                project_root=root,
                golden_stack=GoldenStackPolicy.load(
                    ROOT / "config/autodl-stack-fingerprint.json"
                ),
            )
            output, prompt_id = service._generate_item(
                task["task_id"],
                {
                    "shot_id": "b01",
                    "attempt": "attempt-001",
                    "fingerprint": "a" * 64,
                    "request_path_absolute": attempt / "request.json",
                    "request": object(),
                    "compiled": None,
                },
                InstanceInfo("instance-1", "running", "local", 5.98, 0.0),
                poll_interval=10,
                timeout=1,
            )
            self.assertEqual("existing-prompt", prompt_id)
            self.assertEqual("recovered.mp4", output["filename"])
            self.assertEqual(["history:existing-prompt"], client.calls)

    def test_gold_runtime_overrides_cannot_disable_the_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store, task = self._store_and_task(Path(temporary), gold=True)
            task["runtime_overrides"] = {"download_backpressure": "disabled"}
            with self.assertRaisesRegex(BrollTaskError, "bounded"):
                store.save(task)
            task["runtime_overrides"] = {"shutdown_after_success": False}
            with self.assertRaisesRegex(BrollTaskError, "user-authorized"):
                store.save(task)

    def test_completed_delivery_requires_hashes_and_shutdown_or_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store, task = self._store_and_task(root)
            directory = store.directory(task["task_id"])
            generated = root / "outputs/generated" / task["task_id"] / "b01-attempt-001.mp4"
            delivered = root / "outputs/final" / task["task_id"] / "b01-attempt-001.mp4"
            generated.parent.mkdir(parents=True)
            delivered.parent.mkdir(parents=True)
            generated.write_bytes(b"verified-video")
            delivered.write_bytes(b"verified-video")
            digest = hashlib.sha256(b"verified-video").hexdigest()
            result_path = directory / "h3-requests/b01/attempt-001/result.json"
            result_path.parent.mkdir(parents=True)
            result_path.write_text(
                json.dumps(
                    {
                        "shot_id": "b01",
                        "attempt": "attempt-001",
                        "prompt_id": "p1",
                        "provider_status": "succeeded",
                        "download_path": str(generated),
                        "output_sha256": digest,
                    }
                ),
                encoding="utf-8",
            )
            manifest = {
                "task_id": task["task_id"],
                "shutdown_verified": True,
                "clips": [
                    {
                        "shot_id": "b01",
                        "attempt": "attempt-001",
                        "path": str(delivered),
                        "sha256": digest,
                        "source_sha256": digest,
                    }
                ],
            }
            (directory / "delivery-manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            service = BrollAutoDLService.__new__(BrollAutoDLService)
            service.tasks = store
            self.assertEqual(1, len(service._completed_results(task["task_id"])))
            delivered.write_bytes(b"tampered")
            self.assertIsNone(service._completed_results(task["task_id"]))


if __name__ == "__main__":
    unittest.main()
