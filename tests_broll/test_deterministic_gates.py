from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator

from broll_video.cli import _parser, main as cli_main
from broll_video.gold_contract import compile_gold_requests, prepare_h3_prompts
from broll_video.producer import (
    next_action,
    validate_approved_generate_set,
    validate_shot_plan,
    validate_storyboard_sample,
)
from broll_video.task import (
    APPROVAL_SOURCE_EXPLICIT_USER,
    BrollTaskError,
    BrollTaskStore,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DeterministicGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.srt"
        self.source.write_text(
            "1\n00:00:00,000 --> 00:00:06,000\n旧方法和新方法的关系发生了变化。\n",
            encoding="utf-8",
        )
        self.store = BrollTaskStore(self.root / "work/tasks")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _task(self) -> dict:
        return self.store.create(
            name="deterministic",
            source_srt=self.source,
            ratio="16:9",
            deterministic_gates=True,
        )

    def _write_stage_one(
        self, task: dict, *, necessary_text: list[str] | None = None
    ) -> tuple[Path, dict]:
        directory = self.store.directory(task["task_id"])
        texts = ["旧方法", "新方法"] if necessary_text is None else necessary_text
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
                    {"source": "style reference", "sha256": "a" * 64, "scope": "all"}
                ],
                "talking_head_transition": [
                    {"source": "edit reference", "sha256": "b" * 64, "scope": "all"}
                ],
            },
            "decisions": {
                "subject_language": "abstract comparison cards",
                "material_language": "matte paper and simple icons",
                "space_language": "left-right comparison field",
                "character_scale_proportion": "no character required",
                "palette_exposure_lighting": "dark blue with amber focus",
                "contrast_density": "high contrast and low density",
                "camera_language": "restrained categorical viewpoints",
                "variation_rule": "change a categorical signature at each cut",
                "talking_head_transition": "match exposure and direction",
                "forbidden_elements": [],
            },
        }
        plan = {
            "schema_version": "3.0",
            "task_id": task["task_id"],
            "source_thesis": "比较对象之间的关系变化",
            "audience_start": "观众尚未看见差异",
            "logic_progression": ["旧方法", "对照", "新方法"],
            "emotion_curve": ["疑问", "清楚"],
            "source_duration_seconds": 6.0,
            "coverage_target_percent": 100.0,
            "selected_broll_duration_seconds": 6.0,
            "actual_coverage_percent": 100.0,
            "rhetorical_coverage": [
                {
                    "member_id": "problem_relation_change",
                    "label": "旧方法与新方法的关系变化",
                    "role": "problem",
                    "required": True,
                    "covered_shot_ids": ["b01"],
                }
            ],
            "shots": [
                {
                    "shot_id": "b01",
                    "source_range": "0.0-6.0s",
                    "source_start_seconds": 0.0,
                    "source_end_seconds": 6.0,
                    "source_quote": "旧方法和新方法的关系发生了变化",
                    "visual_job": "让比较对象和关系推进可见",
                    "scene_and_reason": "用对照卡片、图标和空间关系推进信息",
                    "scene_design": {
                        "subject": "旧方法与新方法两组信息卡",
                        "setting": "左右对照的信息空间",
                        "visual_progress": "先建立比较对象，再用位置和连接关系显示方法变化",
                        "visual_style_application": "纸张卡片、图标和高对比色块",
                        "talking_head_transition": "从左侧视线方向进入比较空间",
                    },
                    "style_route": "approved comparison-card family",
                    "text_strategy": "concept_ui" if texts else "none",
                    "sequence_mode": "multi_shot",
                    "beats": [
                        {
                            "time": "0-3s",
                            "start_seconds": 0.0,
                            "end_seconds": 3.0,
                            "spoken_addition": "先确定讨论对象",
                            "visual_content": "左侧旧方法卡与限制图标形成一组关系",
                            "shot_number": 1,
                            "framing": "左侧对照区域",
                            "camera": "稳定观察",
                            "shot_size": "wide",
                            "camera_angle": "eye_level",
                            "viewpoint": "comparison_left",
                            "transition_in": "start",
                        },
                        {
                            "time": "3-6s",
                            "start_seconds": 3.0,
                            "end_seconds": 6.0,
                            "spoken_addition": "再看关系如何变化",
                            "visual_content": "右侧新方法卡与连接图标构成明确对照",
                            "shot_number": 2,
                            "framing": "右侧对照区域",
                            "camera": "切换到第二观察位",
                            "shot_size": "medium",
                            "camera_angle": "high_angle",
                            "viewpoint": "comparison_right",
                            "transition_in": "match_cut",
                        },
                    ],
                    "transitions": ["对照线保持方向一致"],
                    "continuity_anchor": "同一套卡片材质和左右关系",
                    "necessary_text": texts,
                    "sound_intent": "纸卡移动和图标扣合声",
                    "generation_duration": 6,
                }
            ],
        }
        (directory / "visual-lock.json").write_text(
            json.dumps(visual_lock, ensure_ascii=False), encoding="utf-8"
        )
        (directory / "visual-lock.md").write_text(
            "# 视觉锁人工审阅\n", encoding="utf-8"
        )
        (directory / "shot-plan.json").write_text(
            json.dumps(plan, ensure_ascii=False), encoding="utf-8"
        )
        (directory / "shot-plan.md").write_text(
            "# 镜头计划人工审阅\n", encoding="utf-8"
        )
        return directory, plan

    def _write_storyboards(
        self, task: dict, plan: dict, *, necessary_text: list[str] | None = None
    ) -> dict:
        directory = self.store.directory(task["task_id"])
        texts = ["旧方法", "新方法"] if necessary_text is None else necessary_text
        panel_texts = [[texts[0]], [], [texts[1]], []] if texts else [[], [], [], []]
        prompt_lines: list[str] = []
        panels = []
        panel_specs = [
            (1, 0.0, 1.5, 1, "start", "wide", "eye_level", "comparison_left"),
            (2, 1.5, 3.0, 1, "continue", "wide", "eye_level", "comparison_left"),
            (3, 3.0, 4.5, 2, "match_cut", "medium", "high_angle", "comparison_right"),
            (4, 4.5, 6.0, 2, "continue", "medium", "high_angle", "comparison_right"),
        ]
        for number, start, end, shot_number, transition, size, angle, viewpoint in panel_specs:
            required_text = panel_texts[number - 1]
            prompt_lines.extend(
                [
                    f"Panel {number}: abstract cards, icons, and spatial relationships",
                    f"Panel {number} required_text: "
                    + json.dumps(required_text, ensure_ascii=False, separators=(",", ":")),
                ]
            )
            panels.append(
                {
                    "panel_number": number,
                    "time": f"{start:.1f}-{end:.1f}s",
                    "start_seconds": start,
                    "end_seconds": end,
                    "spoken_addition": f"信息推进 {number}",
                    "shot_number": shot_number,
                    "framing": "抽象对照卡片构图",
                    "camera": "克制观察",
                    "shot_size": size,
                    "camera_angle": angle,
                    "viewpoint": viewpoint,
                    "transition_in": transition,
                    "visual_content": "标题、对照卡片、图标和空间关系共同推进当前信息",
                    "continuity_anchor": "同一套纸卡、图标和左右关系",
                    "text_strategy": "concept_ui" if required_text else "none",
                    "required_text": required_text,
                }
            )
        raw = directory / "storyboards/raw/b01-board-01.png"
        review = directory / "storyboards/review/b01-board-01-review.png"
        prompt = directory / "storyboards/prompts/b01-board-01.md"
        raw.write_bytes(b"raw four-panel board")
        review.write_bytes(b"review four-panel board")
        prompt.write_text("\n".join(prompt_lines), encoding="utf-8")
        images: list[str] = []
        for index in range(1, 4):
            image = directory / f"storyboards/generation/b01-{index}.png"
            image.write_bytes(f"anchor-{index}".encode())
            images.append(str(image.relative_to(directory)))
        board_plan = {
            "schema_version": "1.0",
            "task_id": task["task_id"],
            "shots": [
                {
                    "shot_id": "b01",
                    "board_count": 1,
                    "reason": "one board is enough for this comparison progression",
                    "semantic_groups": [
                        {
                            "board_number": 1,
                            "start_seconds": 0.0,
                            "end_seconds": 6.0,
                            "semantic_purpose": "identify the objects and advance their comparison",
                        }
                    ],
                }
            ],
        }
        manifest_shot = {
            "shot_id": "b01",
            "boards": [
                {
                    "board_id": "b01-board-01",
                    "raw_board": str(raw.relative_to(directory)),
                    "review_board": str(review.relative_to(directory)),
                    "imagine_prompt": str(prompt.relative_to(directory)),
                    "panels": panels,
                }
            ],
            "generation_images": images,
            "generation_anchor_times_seconds": [0.0, 3.0, 6.0],
        }
        sample = {
            "schema_version": "3.0",
            "task_id": task["task_id"],
            "generator": "codex-imagine",
            "shots": [deepcopy(manifest_shot)],
        }
        manifest = {
            "schema_version": "3.0",
            "task_id": task["task_id"],
            "generator": "codex-imagine",
            "h3_visual_guard": (
                "保持已批准的抽象对照卡片、图标、纸张材质、左右空间关系、暗蓝与琥珀配色，不添加无关漂亮背景。"
            ),
            "shots": [manifest_shot],
        }
        (directory / "storyboard-board-plan.json").write_text(
            json.dumps(board_plan, ensure_ascii=False), encoding="utf-8"
        )
        (directory / "storyboard-sample.json").write_text(
            json.dumps(sample, ensure_ascii=False), encoding="utf-8"
        )
        (directory / "storyboard-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        return manifest

    def test_new_schema_accepts_irrelevant_legacy_extra_without_requiring_it(self) -> None:
        task = self._task()
        _, plan = self._write_stage_one(task)
        schema = json.loads(
            (PROJECT_ROOT / "schemas/broll-shot-plan.schema.json").read_text(
                encoding="utf-8"
            )
        )
        plan["shots"][0]["legacy_unused_note"] = "legacy ignored extra"
        validate_shot_plan(task, plan)
        Draft202012Validator(schema).validate(plan)

        missing_progress = deepcopy(plan)
        del missing_progress["shots"][0]["scene_design"]["visual_progress"]
        with self.assertRaisesRegex(BrollTaskError, "scene_design"):
            validate_shot_plan(task, missing_progress)
        self.assertTrue(list(Draft202012Validator(schema).iter_errors(missing_progress)))

        missing_member = deepcopy(plan)
        missing_member["rhetorical_coverage"][0]["covered_shot_ids"] = []
        with self.assertRaisesRegex(BrollTaskError, "has no covered shot"):
            validate_shot_plan(task, missing_member)

    def test_explicit_approval_freezes_all_stage_one_bytes(self) -> None:
        task = self._task()
        directory, plan = self._write_stage_one(task)
        sample = self._write_storyboards(task, plan)
        sample_payload = {
            "schema_version": "3.0",
            "task_id": task["task_id"],
            "generator": "codex-imagine",
            "shots": [deepcopy(sample["shots"][0])],
        }
        self.assertEqual(
            "awaiting_shot_plan_approval",
            next_action(self.store, task["task_id"])["state"],
        )
        with self.assertRaisesRegex(BrollTaskError, "explicit user approval"):
            validate_storyboard_sample(directory, sample_payload)
        with self.assertRaisesRegex(BrollTaskError, "approval_source"):
            self.store.approve_shot_plan(task["task_id"], approval_source="internal_qa")

        with redirect_stdout(io.StringIO()):
            self.assertEqual(
                0,
                cli_main(
                    [
                        "--project-root",
                        str(self.root),
                        "approve-shot-plan",
                        task["task_id"],
                        "--approval-source",
                        APPROVAL_SOURCE_EXPLICIT_USER,
                    ]
                ),
            )
        approved = self.store.load(task["task_id"])
        receipt = approved["shot_plan_approval"]
        self.assertEqual("explicit_user_instruction", receipt["approval_source"])
        self.assertEqual("visual_lock_and_shot_plan", receipt["approval_scope"])
        self.assertEqual(4, len(receipt["artifacts"]))
        self.assertEqual(64, len(receipt["review_bundle_sha256"]))
        self.assertNotIn("user_event_id", receipt)
        validate_storyboard_sample(directory, sample_payload)

        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            _parser().parse_args(["approve-shot-plan", task["task_id"]])

        with (directory / "shot-plan.md").open("a", encoding="utf-8") as handle:
            handle.write("一个字节变化\n")
        with self.assertRaisesRegex(BrollTaskError, "approve-shot-plan again"):
            validate_storyboard_sample(directory, sample_payload)
        self.assertEqual(
            "awaiting_shot_plan_reapproval",
            next_action(self.store, task["task_id"])["state"],
        )

    def test_structured_signature_changes_and_one_take_exemption(self) -> None:
        task = self._task()
        _, plan = self._write_stage_one(task)
        invalid = deepcopy(plan)
        invalid["shots"][0]["beats"][1].update(
            {
                "shot_size": "wide",
                "camera_angle": "eye_level",
                "viewpoint": "comparison_left",
            }
        )
        with self.assertRaisesRegex(BrollTaskError, "must change shot_size"):
            validate_shot_plan(task, invalid)

        one_take = deepcopy(plan)
        one_take["shots"][0]["sequence_mode"] = "one_take"
        one_take["shots"][0]["beats"][1].update(
            {
                "shot_number": 1,
                "transition_in": "continue",
                "shot_size": "wide",
                "camera_angle": "eye_level",
                "viewpoint": "comparison_left",
            }
        )
        validate_shot_plan(task, one_take)

    def test_required_text_transfer_is_exact_but_not_a_semantic_ai_claim(self) -> None:
        task = self._task()
        directory, plan = self._write_stage_one(task)
        manifest = self._write_storyboards(task, plan)
        self.store.approve_shot_plan(
            task["task_id"], approval_source=APPROVAL_SOURCE_EXPLICIT_USER
        )
        sample = json.loads(
            (directory / "storyboard-sample.json").read_text(encoding="utf-8")
        )
        validate_storyboard_sample(directory, sample)
        self.assertNotIn("action_result", manifest["shots"][0]["boards"][0]["panels"][0])

        prompt_path = directory / "storyboards/prompts/b01-board-01.md"
        prompt_path.write_text(
            prompt_path.read_text(encoding="utf-8").replace(
                'Panel 3 required_text: ["新方法"]',
                "Panel 3 required_text: []",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(BrollTaskError, "exact required_text marker"):
            validate_storyboard_sample(directory, sample)

        empty_task = self._task()
        empty_directory, empty_plan = self._write_stage_one(
            empty_task, necessary_text=[]
        )
        self._write_storyboards(empty_task, empty_plan, necessary_text=[])
        self.store.approve_shot_plan(
            empty_task["task_id"], approval_source=APPROVAL_SOURCE_EXPLICIT_USER
        )
        empty_sample = json.loads(
            (empty_directory / "storyboard-sample.json").read_text(encoding="utf-8")
        )
        validate_storyboard_sample(empty_directory, empty_sample)

    def test_semantic_group_check_reports_only_time_boundary_mismatch(self) -> None:
        task = self._task()
        directory, plan = self._write_stage_one(task)
        self._write_storyboards(task, plan)
        self.store.approve_shot_plan(
            task["task_id"], approval_source=APPROVAL_SOURCE_EXPLICIT_USER
        )
        sample = json.loads(
            (directory / "storyboard-sample.json").read_text(encoding="utf-8")
        )
        sample["shots"][0]["boards"][0]["panels"][0]["start_seconds"] = 0.25
        with self.assertRaisesRegex(
            BrollTaskError, "semantic-group time boundary"
        ):
            validate_storyboard_sample(directory, sample)

    def test_variant_ledger_and_full_manifest_generation_set_are_closed(self) -> None:
        task = self._task()
        directory, plan = self._write_stage_one(task)
        self._write_storyboards(task, plan)
        task["inheritance_policy"] = {
            "mode": "resume",
            "source_task_id": "prior-task",
        }
        task["variant_ledger"] = {
            "approved_generate_set": ["b01"],
            "assets": [
                {
                    "asset_id": f"asset-{index}",
                    "disposition": disposition,
                    "variant_role": variant_role,
                }
                for index, (disposition, variant_role) in enumerate(
                    zip(
                        ("retain", "replace", "additive", "archive-only"),
                        ("primary", "backup", "superseded", "archive-only"),
                    ),
                    start=1,
                )
            ],
        }
        self.store.save(task)
        approved = self.store.approve_shot_plan(
            task["task_id"], approval_source=APPROVAL_SOURCE_EXPLICIT_USER
        )
        self.assertEqual(
            ["b01"], approved["shot_plan_approval"]["approved_generate_set"]
        )
        validate_approved_generate_set(approved, ["b01"], context="test manifest")
        with self.assertRaisesRegex(BrollTaskError, "not closed"):
            validate_approved_generate_set(
                approved, ["b01", "b02"], context="test manifest"
            )

        for mode in ("resume", "regenerate", "additive", "replace", "fresh_redesign"):
            candidate = deepcopy(approved)
            candidate["inheritance_policy"] = {
                "mode": mode,
                "source_task_id": None if mode == "fresh_redesign" else "prior-task",
            }
            BrollTaskStore.validate(candidate)

        mutated = deepcopy(approved)
        mutated["variant_ledger"]["assets"][0]["disposition"] = "replace"
        self.store.save(mutated)
        sample = json.loads(
            (directory / "storyboard-sample.json").read_text(encoding="utf-8")
        )
        with self.assertRaisesRegex(BrollTaskError, "approve-shot-plan again"):
            validate_storyboard_sample(directory, sample)

    def test_approval_receipts_and_compile_gate_keep_exact_scope(self) -> None:
        task = self._task()
        directory, plan = self._write_stage_one(task)
        self._write_storyboards(task, plan)
        self.store.approve_shot_plan(
            task["task_id"], approval_source=APPROVAL_SOURCE_EXPLICIT_USER
        )
        with self.assertRaisesRegex(BrollTaskError, "explicit user instruction"):
            self.store.approve_storyboard_sample(task["task_id"])
        sample_approved = self.store.approve_storyboard_sample(
            task["task_id"], approval_source=APPROVAL_SOURCE_EXPLICIT_USER
        )
        sample_receipt = sample_approved["storyboard_sample_approval"]
        self.assertEqual(
            "representative_storyboard_sample", sample_receipt["approval_scope"]
        )
        self.assertEqual(64, len(sample_receipt["review_bundle_sha256"]))

        prepare_h3_prompts(self.store, task["task_id"])
        storyboard_approved = self.store.approve_storyboards(
            task["task_id"], approval_source=APPROVAL_SOURCE_EXPLICIT_USER
        )
        storyboard_receipt = storyboard_approved["storyboard_approval"]
        self.assertEqual(
            "full_storyboards_and_h3_prompts", storyboard_receipt["approval_scope"]
        )
        self.assertEqual(64, len(storyboard_receipt["review_bundle_sha256"]))
        task_schema = json.loads(
            (PROJECT_ROOT / "schemas/broll-task.schema.json").read_text(encoding="utf-8")
        )
        manifest_schema = json.loads(
            (PROJECT_ROOT / "schemas/storyboard-manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator(task_schema).validate(storyboard_approved)
        Draft202012Validator(manifest_schema).validate(
            json.loads(
                (directory / "storyboard-manifest.json").read_text(encoding="utf-8")
            )
        )
        self.assertEqual(2, compile_gold_requests(self.store, task["task_id"])["requests"])

        manifest_path = directory / "storyboard-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["shots"][0]["shot_id"] = "b02"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(BrollTaskError, "not closed"):
            compile_gold_requests(self.store, task["task_id"])


if __name__ == "__main__":
    unittest.main()
