"""Fail-closed prompt contract for the three-stage H3 production path."""

from __future__ import annotations

from typing import Any
import re

from .models import H3InputError, H3Request


PROMPT_MAX_CHARACTERS = 1600
VISUAL_GUARD = (
    "只使用参考图中已有的主体、物体、文字和空间，不新增故事、人物、物件、场景或文字。"
)
SFX_ONLY_GUARD = (
    "只允许画面内可见动作和环境产生的同步音效；"
    "不要人声、口播、旁白、对话、歌唱、音乐或画外声。"
)
COMPILED_SFX_ONLY_GUARD = (
    "Only these synchronized diegetic environmental and visible physical-action "
    "sounds are audible. No dialogue, narration, voice, singing, music, or off-screen "
    "sound. Do not infer speech from text or reference images; use silence when no "
    "sound is specified in integrated_multimodal_description."
)

_FORBIDDEN_SCRIPT_FIELDS = re.compile(
    r"(?:spoken_addition|source_quote|口播原文[:：]|逐字稿[:：]|SRT\s*原文[:：])",
    re.IGNORECASE,
)
_VOICE_OR_MUSIC_IN_SFX = re.compile(
    r"(?:music|soundtrack|score|melody|sing|humming|voice|dialogue|narration|speech|"
    r"音乐|配乐|歌曲|歌声|人声|对话|口播|旁白|说话|台词)",
    re.IGNORECASE,
)
_POSITIVE_VOICE_OR_MUSIC = re.compile(
    r"(?:(?:背景音乐|配乐|音乐|人声|对话|旁白|口播|歌声|music|soundtrack|voice|dialogue|narration)"
    r".{0,16}(?:响起|播放|加入|出现|说|朗读|演唱|play|add|include|speak|sing)|"
    r"(?:响起|播放|加入|出现|说|朗读|演唱|play|add|include|speak|sing)"
    r".{0,16}(?:背景音乐|配乐|音乐|人声|对话|旁白|口播|歌声|music|soundtrack|voice|dialogue|narration))",
    re.IGNORECASE,
)


def validate_h3_motion_prompt(
    prompt: Any,
    *,
    anchor_count: int,
    audio_policy: str,
    duration: int | None = None,
    ratio: str | None = None,
    label: str = "H3 prompt",
) -> str:
    """Check the generated script without restricting valid visual direction."""

    text = str(prompt or "").strip()
    if not text or len(text) > PROMPT_MAX_CHARACTERS:
        raise H3InputError(
            f"{label} must contain 1-{PROMPT_MAX_CHARACTERS} characters"
        )
    if not 1 <= anchor_count <= 9:
        raise H3InputError(f"{label} has an invalid reference-image count")
    if _FORBIDDEN_SCRIPT_FIELDS.search(text):
        raise H3InputError(f"{label} contains raw narration/source-script fields")
    if duration is not None and ratio is not None:
        expected_header = f"图1至图{anchor_count}是这个{duration}秒、{ratio}视频"
        if not text.startswith(expected_header):
            raise H3InputError(
                f"{label} duration, ratio or reference count differs from the request"
            )
    visual_body = text.rsplit("同步音效：", 1)[0]
    if _POSITIVE_VOICE_OR_MUSIC.search(visual_body):
        raise H3InputError(f"{label} positively requests voice or music")
    if audio_policy != "sfx_only":
        raise H3InputError(f"{label} requires audio_policy=sfx_only")
    if text.count("同步音效：") != 1 or not text.endswith(SFX_ONLY_GUARD):
        raise H3InputError(f"{label} does not end with the locked SFX-only clause")
    sfx = text.rsplit("同步音效：", 1)[1].removesuffix(SFX_ONLY_GUARD).strip(" 。")
    if not sfx or _VOICE_OR_MUSIC_IN_SFX.search(sfx):
        raise H3InputError(
            f"{label} SFX field may contain only visible-action and environmental sounds"
        )
    return text


def validate_h3_upload_gate(request: H3Request, compiled: Any) -> None:
    """Last gate before any media upload or Comfy ``/prompt`` submission."""

    if request.production_contract != "agent-know-gold-v1":
        return
    if request.provider_profile != "precision_keyframes":
        raise H3InputError("H3 upload gate requires precision_keyframes")
    validate_h3_motion_prompt(
        request.prompt,
        anchor_count=len(request.media),
        audio_policy=request.audio_policy,
        duration=request.duration,
        ratio=request.ratio,
        label="H3 upload prompt",
    )
    conditioning = extract_final_h3_conditioning(compiled)
    motion_body = request.prompt.rsplit("同步音效：", 1)[0].rstrip()
    if motion_body not in conditioning:
        raise H3InputError("final H3 conditioning no longer contains the frozen generation script")
    if not conditioning.startswith("How the reference pictures align with the target video"):
        raise H3InputError("final H3 conditioning changed the approved FL2VA structure")
    if "integrated_multimodal_description:" not in conditioning:
        raise H3InputError("final H3 conditioning lacks integrated_multimodal_description")
    if "overall_soundscape:" not in conditioning:
        raise H3InputError("final H3 conditioning lacks overall_soundscape")
    if COMPILED_SFX_ONLY_GUARD not in conditioning:
        raise H3InputError("final H3 conditioning changed the locked SFX-only clause")
    if not re.search(r"non_diegetic_music:\s*N/A\s*$", conditioning):
        raise H3InputError("final H3 conditioning must end with non_diegetic_music: N/A")
    if _FORBIDDEN_SCRIPT_FIELDS.search(conditioning):
        raise H3InputError("final H3 conditioning leaked raw narration/source-script fields")


def extract_final_h3_conditioning(compiled: Any) -> str:
    """Return the exact conditioning string that Comfy will receive.

    This deliberately reads the compiled workflow rather than the stage-two
    generation script.  The latter is a frozen source input, not the final H3
    conditioning submitted to Comfy.
    """

    try:
        conditioning = str(compiled.prompt["136"]["inputs"]["prompt"]).strip()
    except (AttributeError, KeyError, TypeError) as exc:
        raise H3InputError("H3 workflow cannot locate final conditioning") from exc
    if not conditioning:
        raise H3InputError("H3 workflow final conditioning is empty")
    return conditioning


__all__ = [
    "PROMPT_MAX_CHARACTERS",
    "SFX_ONLY_GUARD",
    "VISUAL_GUARD",
    "extract_final_h3_conditioning",
    "validate_h3_motion_prompt",
    "validate_h3_upload_gate",
]
