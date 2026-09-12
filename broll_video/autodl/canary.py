"""Offline graph checks used by the AutoDL production path."""

from __future__ import annotations

from typing import Any, Mapping

from .graph import CompiledWorkflow


def offline_rtx_frame_canary(compiled: CompiledWorkflow) -> dict[str, Any]:
    """Fail closed when a 4K graph could lose the H3 frame target."""

    rtx_nodes = [
        (node_id, node)
        for node_id, node in compiled.prompt.items()
        if isinstance(node, Mapping)
        and node.get("class_type") == "RTXVideoSuperResolution"
    ]
    if not rtx_nodes:
        return {
            "applicable": False,
            "passed": True,
            "target_frame_count": compiled.frame_count,
            "status": "not_applicable",
        }
    create_nodes = [
        node
        for node in compiled.prompt.values()
        if isinstance(node, Mapping) and node.get("class_type") == "CreateVideo"
    ]
    length_values = [
        node.get("inputs", {}).get("length")
        for node in compiled.prompt.values()
        if isinstance(node, Mapping)
        and node.get("class_type")
        in {"MiniMaxH3ReferenceToVideo", "MiniMaxH3ImageToVideo", "H3Keyframes"}
    ]
    easy_seconds = [
        node.get("inputs", {}).get("seconds")
        for node in compiled.prompt.values()
        if isinstance(node, Mapping) and node.get("class_type") == "MiniMaxH3Easy"
    ]
    rtx_id, rtx_node = rtx_nodes[0]
    rtx_inputs = rtx_node.get("inputs", {})
    target_width = rtx_inputs.get("resize_type.width")
    target_height = rtx_inputs.get("resize_type.height")
    create_inputs = create_nodes[0].get("inputs", {}) if len(create_nodes) == 1 else {}
    checks = {
        "exactly_one_rtx_node": len(rtx_nodes) == 1,
        "exactly_one_create_video_node": len(create_nodes) == 1,
        "h3_length_matches_compiled_frame_count": (
            length_values == [compiled.frame_count]
            or (
                not length_values
                and len(easy_seconds) == 1
                and _easy_h3_frame_count(easy_seconds[0]) == compiled.frame_count
            )
        ),
        "create_video_consumes_rtx_output": create_inputs.get("images") == [rtx_id, 0],
        "fps_is_24": float(create_inputs.get("fps", 0)) == 24.0,
        "target_dimensions_present": isinstance(target_width, int)
        and isinstance(target_height, int)
        and target_width > 0
        and target_height > 0,
    }
    return {
        "applicable": True,
        "mode": "offline_workflow_graph",
        "passed": all(checks.values()),
        "target_frame_count": compiled.frame_count,
        "fps": 24,
        "target_dimensions": [target_width, target_height],
        "checks": checks,
        "status": "passed" if all(checks.values()) else "failed",
    }


def _easy_h3_frame_count(seconds: Any) -> int | None:
    try:
        target_frames = max(5.0, float(seconds) * 24.0)
    except (TypeError, ValueError):
        return None
    return max(0, round((target_frames - 5.0) / 17.0)) * 17 + 5
