from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from broll_video.autodl.graph import FOUR_K_DIMENSIONS
from broll_video.autodl.service import _require_video_dimensions
from broll_video.autodl.workflow import AutoDLWorkflowCompiler
from broll_video.requests import load_request
from broll_video.task import BrollTaskError, BrollTaskStore, task_provider


class BrollFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.srt = self.root / "episode.srt"
        self.srt.write_text(
            "1\n00:00:01,000 --> 00:00:07,000\n我们需要看见这个过程为什么发生。\n",
            encoding="utf-8",
        )
        self.store = BrollTaskStore(self.root / "work/tasks")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _task(self, *, resolution: str = "4K") -> dict:
        return self.store.create(
            name="一期口播",
            source_srt=self.srt,
            ratio="16:9",
            resolution=resolution,
            production_contract=None,
        )

    def _request(self, task: dict) -> Path:
        directory = self.store.directory(task["task_id"])
        generation = directory / "storyboards/generation/b01.png"
        Image.new("RGB", (864, 480), "blue").save(generation)
        path = directory / "h3-requests/b01/attempt-001/request.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "prompt": (
                        "A paper puppet passes a blue gear to the next station. "
                        "Synchronized gear Foley only. No music or voice."
                    ),
                    "duration": 6,
                    "ratio": "16:9",
                    "resolution": task["spec"]["resolution"],
                    "provider": "autodl",
                    "provider_profile": "fast",
                    "audio_policy": "sfx_only",
                    "seed": 42,
                    "media": [
                        {"source": str(generation), "role": "reference_image"}
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_new_tasks_are_autodl_only(self) -> None:
        task = self._task()
        directory = self.store.directory(task["task_id"])
        self.assertEqual("autodl", task_provider(task))
        self.assertEqual("autodl-comfy-h3", task["spec"]["backend"])
        self.assertEqual(
            directory / "provider/autodl",
            self.store.provider_directory(task["task_id"]),
        )
        self.assertTrue((directory / "provider/autodl").is_dir())

    def test_budget_allows_explicit_fifty_but_defaults_to_twenty(self) -> None:
        self.assertEqual(20.0, self._task()["budget"]["hard_limit"])
        task = self.store.create(
            name="五十预算", source_srt=self.srt, ratio="16:9", budget_cny=50
        )
        self.assertEqual(50.0, task["budget"]["hard_limit"])
        with self.assertRaisesRegex(BrollTaskError, "0-50 CNY"):
            self.store.create(
                name="超预算", source_srt=self.srt, ratio="16:9", budget_cny=50.01
            )

    def test_request_provider_must_be_autodl(self) -> None:
        task = self._task()
        request_path = self._request(task)
        load_request(request_path, expected_provider="autodl")
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        payload["provider"] = "removed-provider"
        request_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "provider must be autodl"):
            load_request(request_path)

    def test_only_base_h3_or_cloud_4k_are_task_outputs(self) -> None:
        with self.assertRaises(BrollTaskError):
            self._task(resolution="2K")

    def test_4k_request_compiles_cloud_rtx_target_dimensions(self) -> None:
        task = self._task()
        request = load_request(self._request(task), expected_provider="autodl")
        compiled = AutoDLWorkflowCompiler().compile(request)
        self.assertEqual("RTXVideoSuperResolution", compiled.prompt["149"]["class_type"])
        self.assertEqual("target dimensions", compiled.prompt["149"]["inputs"]["resize_type"])
        self.assertEqual(3840, compiled.prompt["149"]["inputs"]["resize_type.width"])
        self.assertEqual(2160, compiled.prompt["149"]["inputs"]["resize_type.height"])
        self.assertEqual(["149", 0], compiled.prompt["130"]["inputs"]["images"])

    def test_fast_development_profile_keeps_four_step_sage(self) -> None:
        task = self._task()
        request = load_request(self._request(task), expected_provider="autodl")
        compiled = AutoDLWorkflowCompiler().compile(request)
        self.assertEqual("PathchSageAttentionKJ", compiled.prompt["145"]["class_type"])
        self.assertEqual("auto", compiled.prompt["145"]["inputs"]["sage_attention"])
        self.assertEqual(4, compiled.prompt["124"]["inputs"]["steps"])

    def test_every_ratio_has_an_explicit_divisible_4k_target(self) -> None:
        self.assertEqual(
            {
                "21:9": (3840, 1648),
                "16:9": (3840, 2160),
                "4:3": (4096, 3072),
                "1:1": (3840, 3840),
                "3:4": (3072, 4096),
                "9:16": (2160, 3840),
            },
            FOUR_K_DIMENSIONS,
        )
        for width, height in FOUR_K_DIMENSIONS.values():
            self.assertEqual(0, width % 8)
            self.assertEqual(0, height % 8)

    def test_delivery_rejects_non_target_dimensions(self) -> None:
        media_info = {
            "checked": True,
            "probe": {
                "streams": [
                    {"codec_type": "video", "width": 1920, "height": 1080}
                ]
            },
        }
        with self.assertRaises(BrollTaskError):
            _require_video_dimensions(media_info, (3840, 2160))


if __name__ == "__main__":
    unittest.main()
