from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest

from PIL import Image

from broll_video.autodl.workflow import AutoDLWorkflowCompiler
from broll_video.autodl.pricing import AutoDLPricingCatalog
from broll_video.autodl.readiness import GoldenStackPolicy
from broll_video.autodl.service import BrollAutoDLService
from broll_video.gold_contract import (
    compile_gold_requests,
    prepare_h3_prompts,
    validate_gold_request_set,
)
from broll_video.h3.models import H3InputError
from broll_video.h3.prompt_gate import validate_h3_motion_prompt
from broll_video.producer import (
    next_action,
    validate_shot_plan,
    validate_storyboard_manifest,
    validate_storyboard_sample,
)
from broll_video.requests import load_request
from broll_video.task import (
    APPROVAL_SOURCE_EXPLICIT_USER,
    GOLD_PRODUCTION_CONTRACT,
    THREE_STAGE_WORKFLOW_CONTRACT,
    BrollTaskError,
    BrollTaskStore,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class GoldProductionContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.srt"
        self.source.write_text(
            "1\n00:00:00,000 --> 00:00:06,000\n真实任务会留下可复用经验。\n",
            encoding="utf-8",
        )
        self.store = BrollTaskStore(self.root / "work/tasks")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _task(self) -> dict:
        return self.store.create(
            name="gold",
            source_srt=self.source,
            ratio="16:9",
            resolution="4K",
        )

    def _write_plan_and_boards(
        self, task: dict, *, shot_count: int = 1, anchors: int = 3
    ) -> tuple[Path, dict]:
        directory = self.store.directory(task["task_id"])
        shots = []
        manifest_shots = []
        for shot_number in range(1, shot_count + 1):
            shot_id = f"b{shot_number:02d}"
            source_start = float((shot_number - 1) * 6)
            source_end = source_start + 6.0
            shots.append(
                {
                    "shot_id": shot_id,
                    "source_range": f"{source_start:.1f}-{source_end:.1f}s",
                    "source_start_seconds": source_start,
                    "source_end_seconds": source_end,
                    "source_quote": "THIS SOURCE QUOTE MUST NEVER ENTER THE H3 PROMPT",
                    "visual_job": "解释机制",
                    "scene_and_reason": "一枚实体经验块从错误结果中凝结，再被下一个工作台调用",
                    "scene_design": {
                        "subject": "同一枚琥珀色实体经验块",
                        "setting": "蓝色轨道连接的两个微缩工作台",
                        "visual_progress": "先让错误经验凝结成可识别资产，再展示它被下一工作台实际调用",
                        "action_chain": "错误件移除后经验块成形并沿轨道扣入下一工作台",
                        "result_state": "经验块与下一工作台接口完成实体扣合",
                        "visual_style_application": "蓝调实体微缩景观、左暖右冷光线和清晰实体材质",
                        "talking_head_transition": "保持口播画面的暗部密度与由左向右运动方向",
                    },
                    "style_route": "已批准的蓝调实体微缩景观",
                    "text_strategy": "none",
                    "sequence_mode": "multi_shot",
                    "beats": [
                        {
                            "time": "0-2s",
                            "start_seconds": 0.0,
                            "end_seconds": 2.0,
                            "spoken_addition": "THIS SPOKEN ADDITION MUST NEVER ENTER THE H3 PROMPT",
                            "start_state": "红色错误件仍卡在蓝色轨道上",
                            "shot_number": 1,
                            "framing": "左前方三分之四中景，经验块与错误件同框",
                            "camera": "轻微推进，保持轨道向右",
                            "transition_in": "start",
                            "visual_content": "红色错误件被取下，琥珀色经验块稳定成形并成为当前信息中心",
                            "shot_size": "medium",
                            "camera_angle": "eye_level",
                            "viewpoint": "workbench_left",
                            "action": "红色错误件被取下，琥珀色经验块稳定成形",
                            "end_state": "琥珀色经验块位于蓝色轨道中央",
                        },
                        {
                            "time": "2-6s",
                            "start_seconds": 2.0,
                            "end_seconds": 6.0,
                            "spoken_addition": "不可进入提示词",
                            "start_state": "琥珀色经验块位于蓝色轨道中央",
                            "shot_number": 2,
                            "framing": "俯拍近景，经验块与下一工作台接口同框",
                            "camera": "沿轨道向右平移",
                            "transition_in": "match_cut",
                            "visual_content": "同一经验块沿轨道进入下一工作台并完成接口扣合",
                            "shot_size": "close_up",
                            "camera_angle": "overhead",
                            "viewpoint": "workbench_right",
                            "action": "同一经验块沿轨道进入下一工作台",
                            "end_state": "经验块与下一工作台接口完成扣合",
                        },
                    ],
                    "transitions": ["同一经验块保持在画面中心，轨道运动方向不变"],
                    "continuity_anchor": "同一枚琥珀色经验块和蓝色轨道",
                    "necessary_text": [],
                    "sound_intent": "实体扣合和轨道滑动声；无背景音乐、无人声、无旁白",
                    "generation_duration": 6,
                }
            )
            raw = directory / "storyboards/raw" / f"{shot_id}-board-01.png"
            review = directory / "storyboards/review" / f"{shot_id}-board-01-review.png"
            prompt = directory / "storyboards/prompts" / f"{shot_id}-board-01.md"
            Image.new("RGB", (864, 480), "black").save(raw)
            Image.new("RGB", (864, 480), "navy").save(review)
            prompt.write_text(
                "\n".join(
                    line
                    for index in range(1, 5)
                    for line in (
                        f"Panel {index}: approved semantic storyboard panel {index}",
                        f"Panel {index} required_text: []",
                    )
                ),
                encoding="utf-8",
            )
            images = []
            for index in range(1, anchors + 1):
                image = directory / "storyboards/generation" / f"{shot_id}-{index}.png"
                Image.new("RGB", (864, 480), (index * 20, 40, 80)).save(image)
                images.append(str(image.relative_to(directory)))
            panel_specs = [
                (1, 0.0, 1.5, 1, "start", "medium", "eye_level", "workbench_left"),
                (2, 1.5, 3.0, 1, "continue", "medium", "eye_level", "workbench_left"),
                (3, 3.0, 4.5, 2, "match_cut", "close_up", "overhead", "workbench_right"),
                (4, 4.5, 6.0, 2, "continue", "close_up", "overhead", "workbench_right"),
            ]
            manifest_shots.append(
                {
                    "shot_id": shot_id,
                    "boards": [
                        {
                            "board_id": f"{shot_id}-board-01",
                            "raw_board": str(raw.relative_to(directory)),
                            "review_board": str(review.relative_to(directory)),
                            "imagine_prompt": str(prompt.relative_to(directory)),
                            "panels": [
                                {
                                    "panel_number": panel_number,
                                    "time": f"{start:.1f}-{end:.1f}s",
                                    "start_seconds": start,
                                    "end_seconds": end,
                                    "spoken_addition": f"语义增量 {panel_number}",
                                    "shot_number": panel_shot,
                                    "framing": "按语义变化设计的景别、机位与画面方向",
                                    "camera": "与动作一致的克制运镜",
                                    "shot_size": shot_size,
                                    "camera_angle": camera_angle,
                                    "viewpoint": viewpoint,
                                    "transition_in": transition,
                                    "visual_content": f"第 {panel_number} 格的可见信息推进",
                                    "continuity_anchor": "同一琥珀色经验块、蓝色轨道与运动方向",
                                    "text_strategy": "none",
                                    "required_text": [],
                                }
                                for panel_number, start, end, panel_shot, transition, shot_size, camera_angle, viewpoint in panel_specs
                            ],
                        }
                    ],
                    "generation_images": images,
                    "generation_anchor_times_seconds": [
                        round(index * 6.0 / (anchors - 1), 3)
                        for index in range(anchors)
                    ],
                }
            )
        plan = {
            "schema_version": "3.0",
            "task_id": task["task_id"],
            "source_thesis": "真实任务中的经验需要被编译后复用",
            "audience_start": "观众以为搜得到就等于会使用",
            "logic_progression": ["错误", "提炼", "复用"],
            "emotion_curve": ["困惑", "清楚"],
            "source_duration_seconds": float(shot_count * 6),
            "coverage_target_percent": 100.0,
            "selected_broll_duration_seconds": float(shot_count * 6),
            "actual_coverage_percent": 100.0,
            "rhetorical_coverage": [
                {
                    "member_id": f"experience_reuse_{index}",
                    "label": f"经验复用单元 {index}",
                    "role": "chapter",
                    "required": True,
                    "covered_shot_ids": [shot["shot_id"]],
                }
                for index, shot in enumerate(shots, start=1)
            ],
            "shots": shots,
        }
        (directory / "shot-plan.json").write_text(
            json.dumps(plan, ensure_ascii=False), encoding="utf-8"
        )
        (directory / "shot-plan.md").write_text("# 完整镜头计划\n", encoding="utf-8")
        (directory / "visual-lock.md").write_text("# 已批准视觉家族\n", encoding="utf-8")
        visual_lock = {
            "schema_version": "1.0",
            "task_id": task["task_id"],
            "task_source_binding": {
                "annotations_applied": [],
                "input_sha256s_applied": [],
                "forbidden_applied": [],
                "existing_design_scope": "none",
            },
            "references": {
                "content_scene_style": [
                    {"source": "user style reference", "sha256": "a" * 64, "scope": "all storyboards"}
                ],
                "talking_head_transition": [
                    {"source": "talking-head reference", "sha256": "b" * 64, "scope": "palette and edit rhythm"}
                ],
            },
            "decisions": {
                "subject_language": "anonymous physical miniature objects",
                "material_language": "matte physical miniature materials",
                "space_language": "connected workbench spaces",
                "character_scale_proportion": "one stable miniature scale",
                "palette_exposure_lighting": "dark blue with warm amber focus",
                "contrast_density": "high contrast and low background density",
                "camera_language": "motivated restrained camera moves",
                "variation_rule": "keep the visual family but do not repeat one room or composition without motivation",
                "talking_head_transition": "match exposure, direction and cut rhythm",
                "forbidden_elements": [],
            },
        }
        (directory / "visual-lock.json").write_text(
            json.dumps(visual_lock, ensure_ascii=False), encoding="utf-8"
        )
        board_plan = {
            "schema_version": "1.0",
            "task_id": task["task_id"],
            "shots": [
                {
                    "shot_id": shot["shot_id"],
                    "board_count": 1,
                    "reason": "four panels carry the complete semantic action chain",
                    "semantic_groups": [
                        {
                            "board_number": 1,
                            "start_seconds": 0.0,
                            "end_seconds": 6.0,
                            "semantic_purpose": "establish, transform and deliver the reusable experience block",
                        }
                    ],
                }
                for shot in shots
            ],
        }
        (directory / "storyboard-board-plan.json").write_text(
            json.dumps(board_plan, ensure_ascii=False), encoding="utf-8"
        )
        sample = {
            "schema_version": "3.0",
            "task_id": task["task_id"],
            "generator": "codex-imagine",
            "shots": [manifest_shots[0]],
        }
        (directory / "storyboard-sample.json").write_text(
            json.dumps(sample, ensure_ascii=False), encoding="utf-8"
        )
        manifest = {
            "schema_version": "3.0",
            "task_id": task["task_id"],
            "generator": "codex-imagine",
            "h3_visual_guard": (
                "保持已批准的蓝调实体微缩景观、琥珀色主体、左暖右冷灯光、物件尺度和空间连续性，不增加新主体。"
            ),
            "shots": manifest_shots,
        }
        (directory / "storyboard-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        return directory, manifest

    def _approve(self, task: dict) -> tuple[Path, dict]:
        directory, manifest = self._write_plan_and_boards(task)
        self.store.approve_shot_plan(
            task["task_id"], approval_source=APPROVAL_SOURCE_EXPLICIT_USER
        )
        self.store.approve_storyboard_sample(
            task["task_id"], approval_source=APPROVAL_SOURCE_EXPLICIT_USER
        )
        prepare_h3_prompts(self.store, task["task_id"])
        manifest = json.loads(
            (directory / "storyboard-manifest.json").read_text(encoding="utf-8")
        )
        self.store.approve_storyboards(
            task["task_id"], approval_source=APPROVAL_SOURCE_EXPLICIT_USER
        )
        return directory, manifest

    def test_new_task_defaults_are_the_locked_gold_contract(self) -> None:
        task = self._task()
        spec = task["spec"]
        self.assertEqual(GOLD_PRODUCTION_CONTRACT, spec["production_contract"])
        self.assertEqual(THREE_STAGE_WORKFLOW_CONTRACT, spec["workflow_contract"])
        self.assertEqual("precision_keyframes", spec["provider_profile"])
        self.assertEqual("sfx_only", spec["audio_policy"])
        self.assertEqual(2, spec["draws_per_shot"])
        self.assertEqual(
            "pipelined_single_generate_single_download", spec["execution_order"]
        )
        self.assertEqual(4, spec["download_queue_capacity"])
        self.assertEqual((3840, 2160), (spec["expected_width"], spec["expected_height"]))
        self.assertEqual("pending", task["shot_plan_approval"]["status"])
        self.assertEqual("pending", task["storyboard_sample_approval"]["status"])

    def test_current_gold_contract_rejects_schema2_stage_artifacts(self) -> None:
        task = self._task()
        directory, manifest = self._write_plan_and_boards(task)
        plan = json.loads((directory / "shot-plan.json").read_text(encoding="utf-8"))
        with self.assertRaisesRegex(BrollTaskError, "requires shot-plan schema_version 3.0"):
            validate_shot_plan(task, {**plan, "schema_version": "2.0"})

        self.store.approve_shot_plan(
            task["task_id"], approval_source=APPROVAL_SOURCE_EXPLICIT_USER
        )
        sample = json.loads(
            (directory / "storyboard-sample.json").read_text(encoding="utf-8")
        )
        with self.assertRaisesRegex(
            BrollTaskError, "requires storyboard sample schema_version 3.0"
        ):
            validate_storyboard_sample(
                directory, {**sample, "schema_version": "2.0"}
            )
        with self.assertRaisesRegex(
            BrollTaskError, "requires storyboard manifest schema_version 3.0"
        ):
            validate_storyboard_manifest(
                directory,
                {**manifest, "schema_version": "2.0"},
                require_h3_prompts=False,
            )

    def test_sample_gate_blocks_full_storyboards_until_user_approval(self) -> None:
        task = self._task()
        directory, _ = self._write_plan_and_boards(task)
        self.assertEqual(
            "awaiting_shot_plan_approval",
            next_action(self.store, task["task_id"])["state"],
        )
        self.store.approve_shot_plan(
            task["task_id"], approval_source=APPROVAL_SOURCE_EXPLICIT_USER
        )
        self.assertEqual(
            "awaiting_storyboard_sample_approval",
            next_action(self.store, task["task_id"])["state"],
        )
        self.store.approve_storyboard_sample(
            task["task_id"], approval_source=APPROVAL_SOURCE_EXPLICIT_USER
        )
        self.assertEqual(
            "needs_h3_prompts",
            next_action(self.store, task["task_id"])["state"],
        )
        self.assertTrue((directory / "storyboard-sample.json").is_file())

    def test_compiler_reproduces_gold_inputs_and_rejects_tampering(self) -> None:
        task = self._task()
        directory, manifest = self._approve(task)
        receipt = compile_gold_requests(self.store, task["task_id"])
        self.assertEqual(2, receipt["requests"])
        paths = sorted(directory.glob("h3-requests/b01/attempt-*/request.json"))
        self.assertEqual(2, len(paths))
        request = load_request(paths[0], expected_provider="autodl")
        self.assertEqual(GOLD_PRODUCTION_CONTRACT, request.production_contract)
        self.assertEqual("precision_keyframes", request.provider_profile)
        self.assertEqual("sfx_only", request.audio_policy)
        self.assertEqual(3, len(request.media))
        self.assertEqual([0, 72, 144], [asset.frame_index for asset in request.media])
        self.assertLessEqual(len(request.prompt), 1600)
        self.assertTrue(request.prompt.startswith("图1至图3是这个6秒、16:9视频唯一的画面与风格标准"))
        self.assertIn("[Shot 1] 0.0-1.5s", request.prompt)
        self.assertIn("第 1 格的可见信息推进", request.prompt)
        self.assertIn("[Shot 2] At 00:03.000, a match cut reveals", request.prompt)
        self.assertIn("第 4 格的可见信息推进", request.prompt)
        self.assertIn("同一条视频内按已确认的时间与镜头节拍切换", request.prompt)
        self.assertNotIn("Visual purpose", request.prompt)
        self.assertNotIn("一枚实体经验块从错误结果中凝结", request.prompt)
        self.assertNotIn("Continuity anchor", request.prompt)
        self.assertNotIn("THIS SOURCE QUOTE", request.prompt)
        self.assertNotIn("THIS SPOKEN ADDITION", request.prompt)
        self.assertNotIn("无背景音乐、无人声、无旁白", request.prompt)

        with self.assertRaises(H3InputError):
            validate_h3_motion_prompt(
                request.prompt.replace("时间编排：", "source_quote：口播原文\n时间编排："),
                anchor_count=3,
                audio_policy="sfx_only",
            )

        compiled = AutoDLWorkflowCompiler().compile(request)
        self.assertEqual("0, 72, 144", compiled.prompt["136"]["inputs"]["positions"])
        conditioning = compiled.prompt["136"]["inputs"]["prompt"]
        self.assertTrue(
            conditioning.startswith("How the reference pictures align with the target video")
        )
        self.assertIn("integrated_multimodal_description:", conditioning)
        self.assertIn("overall_soundscape: 实体扣合和轨道滑动声", conditioning)
        self.assertTrue(conditioning.endswith("non_diegetic_music: N/A"))
        self.assertNotIn("KEYFRAME ALIGNMENT:", conditioning)
        sampler_steps = [
            node.get("inputs", {}).get("steps")
            for node in compiled.prompt.values()
            if isinstance(node, dict) and node.get("inputs", {}).get("steps") is not None
        ]
        self.assertIn(8, sampler_steps)

        service = BrollAutoDLService(
            self.store,
            AutoDLPricingCatalog.load(PROJECT_ROOT / "config/autodl-pricing.json"),
            object(),
            project_root=self.root,
            golden_stack=GoldenStackPolicy.load(
                PROJECT_ROOT / "config/autodl-stack-fingerprint.json"
            ),
        )
        generation_plan = service.plan_batch(task["task_id"])
        self.assertEqual(2, len(generation_plan["items"]))
        self.assertTrue(
            all(item["profile"] == "precision_keyframes" for item in generation_plan["items"])
        )

        payload = json.loads(paths[0].read_text(encoding="utf-8"))
        payload["provider_profile"] = "fast"
        paths[0].write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(BrollTaskError, "edited after compilation"):
            validate_gold_request_set(self.store.load(task["task_id"]), directory, manifest)

    def test_task_authorized_single_draw_compiles_one_request(self) -> None:
        task = self._task()
        task["spec"]["draws_per_shot"] = 1
        self.store.save(task)
        directory, _ = self._approve(task)

        receipt = compile_gold_requests(self.store, task["task_id"])

        self.assertEqual(1, receipt["draws_per_shot"])
        self.assertEqual(1, receipt["requests"])
        self.assertEqual(
            ["attempt-001"],
            [path.parent.name for path in directory.glob("h3-requests/b01/attempt-*/request.json")],
        )

    def test_authorize_after_offline_plan_commits_frozen_estimate(self) -> None:
        task = self._task()
        self._approve(task)
        compile_gold_requests(self.store, task["task_id"])
        service = BrollAutoDLService(
            self.store,
            AutoDLPricingCatalog.load(PROJECT_ROOT / "config/autodl-pricing.json"),
            object(),
            project_root=self.root,
            golden_stack=GoldenStackPolicy.load(
                PROJECT_ROOT / "config/autodl-stack-fingerprint.json"
            ),
        )
        plan = service.plan_batch(task["task_id"])

        authorized = self.store.authorize_generation(task["task_id"])

        self.assertEqual("authorized", authorized["execution"]["mode"])
        self.assertEqual(
            float(plan["estimated_total_cny"]),
            authorized["budget"]["committed"],
        )

    def test_dense_review_frames_cannot_be_passed_to_h3(self) -> None:
        task = self._task()
        self._write_plan_and_boards(task, shot_count=2, anchors=5)
        self.store.approve_shot_plan(
            task["task_id"], approval_source=APPROVAL_SOURCE_EXPLICIT_USER
        )
        self.store.approve_storyboard_sample(
            task["task_id"], approval_source=APPROVAL_SOURCE_EXPLICIT_USER
        )
        with self.assertRaisesRegex(BrollTaskError, "anchor density"):
            prepare_h3_prompts(self.store, task["task_id"])

    def test_generation_and_download_receipt_run_as_two_bounded_lines(self) -> None:
        task = self._task()
        service = BrollAutoDLService(
            self.store,
            AutoDLPricingCatalog.load(PROJECT_ROOT / "config/autodl-pricing.json"),
            object(),
            project_root=self.root,
            golden_stack=GoldenStackPolicy.load(
                PROJECT_ROOT / "config/autodl-stack-fingerprint.json"
            ),
        )
        events: list[str] = []
        first_download_started = threading.Event()
        allow_first_download_to_finish = threading.Event()
        items = [
            {"shot_id": "one", "attempt": "attempt-001"},
            {"shot_id": "two", "attempt": "attempt-001"},
        ]

        def generate(_task_id, item, _info, **_kwargs):
            if item["shot_id"] == "two":
                self.assertTrue(first_download_started.wait(timeout=1))
                events.append("generate-two")
                allow_first_download_to_finish.set()
            else:
                events.append("generate-one")
            return {"filename": f"{item['shot_id']}.mp4"}, f"prompt-{item['shot_id']}"

        def download(_task_id, _task, item, _info, **_kwargs):
            events.append(f"download-{item['shot_id']}-start")
            if item["shot_id"] == "one":
                first_download_started.set()
                self.assertTrue(allow_first_download_to_finish.wait(timeout=1))
            events.append(f"download-{item['shot_id']}-end")
            return {"shot_id": item["shot_id"]}

        service._generate_item = generate  # type: ignore[method-assign]
        service._download_item = download  # type: ignore[method-assign]
        results = service._run_gold_pipeline(
            task["task_id"],
            task,
            items,
            object(),
            poll_interval=10,
            timeout_per_task=30,
        )
        self.assertEqual(["one", "two"], [item["shot_id"] for item in results])
        self.assertLess(events.index("download-one-start"), events.index("generate-two"))
        self.assertLess(events.index("generate-two"), events.index("download-one-end"))

    def test_confirmed_download_failure_stops_before_another_paid_generation(self) -> None:
        task = self._task()
        service = BrollAutoDLService(
            self.store,
            AutoDLPricingCatalog.load(PROJECT_ROOT / "config/autodl-pricing.json"),
            object(),
            project_root=self.root,
            golden_stack=GoldenStackPolicy.load(
                PROJECT_ROOT / "config/autodl-stack-fingerprint.json"
            ),
        )
        download_started = threading.Event()
        finish_with_failure = threading.Event()
        failure_is_durable = threading.Event()
        generated: list[str] = []
        items = [
            {"shot_id": value, "attempt": "attempt-001"}
            for value in ("one", "two", "three")
        ]

        def generate(_task_id, item, _info, **_kwargs):
            if item["shot_id"] == "two":
                self.assertTrue(download_started.wait(timeout=1))
                finish_with_failure.set()
                self.assertTrue(failure_is_durable.wait(timeout=1))
            generated.append(item["shot_id"])
            return {"filename": f"{item['shot_id']}.mp4"}, f"prompt-{item['shot_id']}"

        def download(_task_id, _task, item, _info, **_kwargs):
            if item["shot_id"] == "one":
                download_started.set()
                self.assertTrue(finish_with_failure.wait(timeout=1))
                failure_is_durable.set()
                raise OSError("network copy failed")
            return {"shot_id": item["shot_id"]}

        service._generate_item = generate  # type: ignore[method-assign]
        service._download_item = download  # type: ignore[method-assign]
        with self.assertRaisesRegex(OSError, "network copy failed"):
            service._run_gold_pipeline(
                task["task_id"],
                task,
                items,
                object(),
                poll_interval=10,
                timeout_per_task=30,
            )
        self.assertEqual(["one", "two"], generated)


if __name__ == "__main__":
    unittest.main()
