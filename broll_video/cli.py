"""Task CLI for the SRT-to-B-roll production workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .producer import next_action
from .task import APPROVAL_SOURCE_EXPLICIT_USER, BrollTaskStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="broll-video")
    parser.add_argument("--project-root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="copy a complete SRT and create one AutoDL B-roll task")
    init.add_argument("--name", required=True)
    init.add_argument("--srt", required=True)
    init.add_argument("--ratio", required=True)
    init.add_argument("--resolution", choices=("768P", "4K"), default="4K")
    init.add_argument("--budget", type=float, default=20.0)
    init.add_argument(
        "--execution", choices=("estimate_only", "authorized"), default="estimate_only"
    )
    init.add_argument("--annotation", action="append", default=[])
    init.add_argument("--input", action="append", default=[])
    init.add_argument("--forbid", action="append", default=[])

    for command in (
        "next",
        "resume",
        "prepare-h3-prompts",
        "compile-h3",
        "authorize",
        "accept",
    ):
        child = sub.add_parser(command)
        child.add_argument("task_id")
    for command in (
        "approve-shot-plan",
        "approve-storyboard-sample",
        "approve-storyboards",
    ):
        child = sub.add_parser(command)
        child.add_argument("task_id")
        child.add_argument(
            "--approval-source",
            required=True,
            choices=(APPROVAL_SOURCE_EXPLICIT_USER,),
            help="must reflect an explicit user instruction; internal QA is not approval",
        )
    revise = sub.add_parser("revise")
    revise.add_argument("task_id")
    revise.add_argument("--shot", action="append", required=True)
    revise.add_argument("--reason", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.project_root).expanduser().resolve()
    store = BrollTaskStore(root / "work" / "tasks")
    try:
        if args.command == "init":
            task = store.create(
                name=args.name,
                source_srt=args.srt,
                ratio=args.ratio,
                resolution=args.resolution,
                budget_cny=args.budget,
                execution_mode=args.execution,
                annotations=args.annotation,
                inputs=args.input,
                forbidden=args.forbid,
                deterministic_gates=True,
            )
            result = {
                "task_id": task["task_id"],
                "task_dir": str(store.directory(task["task_id"])),
                "provider": task["spec"]["provider"],
                "production_contract": task["spec"].get("production_contract"),
            }
        elif args.command in {"next", "resume"}:
            result = next_action(store, args.task_id)
        elif args.command == "approve-shot-plan":
            task = store.approve_shot_plan(
                args.task_id, approval_source=args.approval_source
            )
            result = {
                "task_id": task["task_id"],
                "shot_plan_approval": task["shot_plan_approval"],
            }
        elif args.command == "approve-storyboard-sample":
            task = store.approve_storyboard_sample(
                args.task_id, approval_source=args.approval_source
            )
            result = {
                "task_id": task["task_id"],
                "storyboard_sample_approval": task["storyboard_sample_approval"],
            }
        elif args.command == "approve-storyboards":
            task = store.approve_storyboards(
                args.task_id, approval_source=args.approval_source
            )
            result = {"task_id": task["task_id"], "storyboard_approval": task["storyboard_approval"]}
        elif args.command == "prepare-h3-prompts":
            from .gold_contract import prepare_h3_prompts

            result = prepare_h3_prompts(store, args.task_id)
        elif args.command == "compile-h3":
            from .gold_contract import compile_gold_requests

            result = compile_gold_requests(store, args.task_id)
        elif args.command == "authorize":
            task = store.authorize_generation(args.task_id)
            result = {"task_id": task["task_id"], "execution": task["execution"]}
        elif args.command == "accept":
            task = store.accept(args.task_id)
            result = {"task_id": task["task_id"], "delivery": task["delivery"]}
        elif args.command == "revise":
            task = store.request_revision(
                args.task_id, shot_ids=args.shot, reason=args.reason
            )
            result = {"task_id": task["task_id"], "delivery": task["delivery"]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
