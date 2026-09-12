"""MiniMax H3 V2 request model and deterministic media preflight."""

from __future__ import annotations

from dataclasses import dataclass, field
import base64
import json
import mimetypes
from pathlib import Path
import re
import shutil
import struct
import subprocess
from typing import Any
from urllib.parse import urlparse


MODEL = "MiniMax-H3"
RATIOS = {"adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}
RESOLUTIONS = {"768P", "4K"}
REFINE_2PASS_EXP_MODEL = "minimax_h3_fl2va_pruned_w4a8_mixed.safetensors"
REFINE_2PASS_EXP_STEPS = 3
REFINE_2PASS_EXP_DENOISE = 0.25
REFINE_2PASS_EXP_SCALE = 2
REFINE_2PASS_INT8_EXP_MODEL = "minimax_h3_fl2va_int8_convrot.safetensors"
REFINE_2PASS_INT8_EXP_PASS1_STEPS = 20
REFINE_2PASS_INT8_EXP_STEPS = 3
REFINE_2PASS_INT8_EXP_DENOISE = 0.25
REFINE_2PASS_INT8_EXP_SCALE = 2
IMAGE_ROLES = {"first_frame", "last_frame", "reference_image"}
VIDEO_ROLES = {"reference_video"}
AUDIO_ROLES = {"reference_audio"}
ALL_ROLES = IMAGE_ROLES | VIDEO_ROLES | AUDIO_ROLES
AUDIO_POLICIES = {"silent", "sfx_only", "scripted_music"}
PRODUCTION_CONTRACTS = {"agent-know-gold-v1"}
REFERENCE_SEMANTIC_ROLES = {
    "object_material",
    "scene",
    "style",
    "action",
    "camera",
    "sound",
    "first_frame",
    "keyframe",
    "last_frame",
}
MAX_BODY_BYTES = 64 * 1024 * 1024
MAX_BYTES = {
    "image": 30 * 1024 * 1024,
    "video": 50 * 1024 * 1024,
    "audio": 15 * 1024 * 1024,
}
EXTENSIONS = {
    "image": {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"},
    "video": {".mp4", ".mov"},
    "audio": {".mp3", ".wav"},
}


class H3InputError(ValueError):
    """Raised when a request violates the official H3 V2 contract."""


@dataclass(frozen=True)
class MediaAsset:
    source: str
    role: str
    # These fields are the durable reference-manifest contract.  They are
    # intentionally attached to the asset, rather than inferred from a prompt,
    # so the exact reviewed reference meaning remains fingerprintable.
    source_origin: str | None = None
    rights_note: str | None = None
    semantic_role: str | None = None
    must_preserve: tuple[str, ...] = ()
    may_change: tuple[str, ...] = ()
    used_by: tuple[str, ...] = ()
    prompt_label: str | None = None
    anchor_time_ms: int | None = None
    frame_index: int | None = None

    @property
    def kind(self) -> str:
        if self.role in IMAGE_ROLES:
            return "image"
        if self.role in VIDEO_ROLES:
            return "video"
        if self.role in AUDIO_ROLES:
            return "audio"
        raise H3InputError(f"unsupported media role: {self.role}")


@dataclass(frozen=True)
class PreflightReport:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    request_body_bytes: int | None = None

    @property
    def ok(self) -> bool:
        return not self.errors

    def require_ok(self) -> None:
        if self.errors:
            raise H3InputError("; ".join(self.errors))


@dataclass(frozen=True)
class H3Request:
    prompt: str
    duration: int
    ratio: str
    resolution: str = "4K"
    media: tuple[MediaAsset, ...] = field(default_factory=tuple)
    callback_url: str | None = None
    audio_policy: str = "sfx_only"
    # Local-provider controls. They deliberately stay out of the legacy
    # MiniMax API payload, but are part of the deterministic request fingerprint.
    provider_profile: str = "fast"
    seed: int | None = None
    # These controls are deliberately explicit in an experimental request.  A
    # new experiment revision must get a new profile/template rather than
    # silently changing the pass-2 sampler behind an existing fingerprint.
    refine_pass2_model: str | None = None
    refine_pass2_steps: int | None = None
    refine_pass2_denoise: float | None = None
    refine_pass2_scale: int | None = None
    # This is not a quality toggle.  It is a fingerprinted declaration that
    # the request is the sole authorized experimental canary for its task.
    experimental_canary: bool = False
    production_contract: str | None = None

    def to_payload(self, *, encode_local: bool = True) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": self.prompt}]
        for asset in self.media:
            source = _encode_source(asset) if encode_local else asset.source
            if asset.kind == "image":
                content.append(
                    {"type": "image_url", "image_url": {"url": source}, "role": asset.role}
                )
            elif asset.kind == "video":
                content.append(
                    {"type": "video_url", "video_url": {"url": source}, "role": asset.role}
                )
            else:
                content.append(
                    {"type": "audio_url", "audio_url": {"url": source}, "role": asset.role}
                )
        payload: dict[str, Any] = {
            "model": MODEL,
            "content": content,
            "resolution": self.resolution,
            "duration": self.duration,
            "ratio": self.ratio,
        }
        if self.callback_url:
            payload["callback_url"] = self.callback_url
        return payload


def preflight_request(request: H3Request, *, encode_local: bool = True) -> PreflightReport:
    errors: list[str] = []
    warnings: list[str] = []
    prompt = request.prompt
    if not prompt.strip():
        errors.append("prompt must not be empty")
    if len(prompt) > 7000:
        errors.append("prompt must not exceed 7000 characters")
    if isinstance(request.duration, bool) or not isinstance(request.duration, int):
        errors.append("duration must be an integer")
    elif not 4 <= request.duration <= 15:
        errors.append("duration must be between 4 and 15 seconds")
    if request.ratio not in RATIOS:
        errors.append(f"unsupported ratio: {request.ratio}")
    if request.resolution not in RESOLUTIONS:
        errors.append(f"unsupported resolution: {request.resolution}")
    if request.callback_url and urlparse(request.callback_url).scheme != "https":
        errors.append("callback_url must use https")
    if request.audio_policy not in AUDIO_POLICIES:
        errors.append(f"unsupported audio_policy: {request.audio_policy}")
    if (
        request.production_contract is not None
        and request.production_contract not in PRODUCTION_CONTRACTS
    ):
        errors.append(f"unsupported production_contract: {request.production_contract}")
    if request.provider_profile not in {
        "fast",
        "precision_keyframes",
        "ref_multimodal",
        "fl2v_explicit",
        "precision_timed",
        "precision_timed_h3keyframes",
        "refine_2pass_exp",
        "refine_2pass_int8_exp",
    }:
        errors.append(f"unsupported provider_profile: {request.provider_profile}")
    if request.seed is not None and (
        isinstance(request.seed, bool)
        or not isinstance(request.seed, int)
        or not 0 <= request.seed < 2**63
    ):
        errors.append("seed must be an integer between 0 and 2^63-1")
    if not isinstance(request.experimental_canary, bool):
        errors.append("experimental_canary must be a boolean")
    if request.production_contract == "agent-know-gold-v1":
        if request.provider_profile != "precision_keyframes":
            errors.append("agent-know-gold-v1 requires provider_profile=precision_keyframes")
        if request.resolution != "4K":
            errors.append("agent-know-gold-v1 requires resolution=4K")
        if request.audio_policy not in {"silent", "sfx_only"}:
            errors.append(
                "agent-know-gold-v1 requires audio_policy=silent or sfx_only"
            )
        if len(request.prompt) > 1600:
            errors.append("agent-know-gold-v1 prompt must not exceed 1600 characters")
        if not 3 <= len(request.media) <= 5:
            errors.append("agent-know-gold-v1 requires 3-5 storyboard anchors")
        if any(asset.role != "reference_image" for asset in request.media):
            errors.append("agent-know-gold-v1 accepts reference_image anchors only")

    roles = [asset.role for asset in request.media]
    invalid = [role for role in roles if role not in ALL_ROLES]
    if invalid:
        errors.append(f"unsupported media role: {invalid[0]}")
    if roles.count("first_frame") > 1 or roles.count("last_frame") > 1:
        errors.append("at most one first frame and one last frame are allowed")
    if roles.count("reference_image") > 9:
        errors.append("at most 9 reference images are allowed")
    if roles.count("reference_video") > 3:
        errors.append("at most 3 reference videos are allowed")
    if roles.count("reference_audio") > 3:
        errors.append("at most 3 reference audios are allowed")
    reference_count = sum(role.startswith("reference_") for role in roles)
    if reference_count > 12:
        errors.append("at most 12 mixed reference files are allowed")
    has_frame = any(role in {"first_frame", "last_frame"} for role in roles)
    has_reference = reference_count > 0
    if has_frame and has_reference:
        errors.append("frame mode and reference mode cannot be mixed")
    if "reference_audio" in roles and not any(
        role in {"reference_image", "reference_video"} for role in roles
    ):
        errors.append("reference audio requires a reference image or video")
    if not request.media and request.ratio == "adaptive":
        errors.append("text-to-video requires a concrete ratio")
    if (
        has_frame
        and request.provider_profile not in {"fl2v_explicit", "refine_2pass_exp", "refine_2pass_int8_exp"}
        and request.ratio != "adaptive"
    ):
        errors.append("first/last-frame mode requires ratio=adaptive")
    if request.provider_profile == "fl2v_explicit" and request.ratio == "adaptive":
        errors.append("fl2v_explicit requires a concrete ratio")
    if request.provider_profile in {"refine_2pass_exp", "refine_2pass_int8_exp"}:
        if request.resolution != "4K":
            errors.append(f"{request.provider_profile} requires resolution=4K so RTX remains the final stage")
        if request.ratio == "adaptive":
            errors.append(f"{request.provider_profile} requires a concrete ratio")
        expected_controls = (
            {
                "refine_pass2_model": REFINE_2PASS_EXP_MODEL,
                "refine_pass2_steps": REFINE_2PASS_EXP_STEPS,
                "refine_pass2_denoise": REFINE_2PASS_EXP_DENOISE,
                "refine_pass2_scale": REFINE_2PASS_EXP_SCALE,
            }
            if request.provider_profile == "refine_2pass_exp"
            else {
                "refine_pass2_model": REFINE_2PASS_INT8_EXP_MODEL,
                "refine_pass2_steps": REFINE_2PASS_INT8_EXP_STEPS,
                "refine_pass2_denoise": REFINE_2PASS_INT8_EXP_DENOISE,
                "refine_pass2_scale": REFINE_2PASS_INT8_EXP_SCALE,
            }
        )
        for name, expected in expected_controls.items():
            if getattr(request, name) != expected:
                errors.append(f"{request.provider_profile} requires {name}={expected!r}")
        if request.provider_profile == "refine_2pass_int8_exp":
            if not request.experimental_canary:
                errors.append("refine_2pass_int8_exp requires experimental_canary=true")
            if request.duration != 6 or request.ratio != "4:3":
                errors.append("refine_2pass_int8_exp is restricted to a 6-second 4:3 canary")
        elif request.experimental_canary:
            errors.append("experimental_canary is valid only for refine_2pass_int8_exp")
    elif request.experimental_canary:
        errors.append("experimental_canary is valid only for refine_2pass_int8_exp")
    elif any(
        getattr(request, name) is not None
        for name in (
            "refine_pass2_model",
            "refine_pass2_steps",
            "refine_pass2_denoise",
            "refine_pass2_scale",
        )
    ):
        errors.append("refine pass-2 controls are valid only for an experimental refine provider profile")

    for asset in request.media:
        if asset.semantic_role and asset.semantic_role not in REFERENCE_SEMANTIC_ROLES:
            errors.append(f"unsupported semantic reference role: {asset.semantic_role}")
        if asset.anchor_time_ms is not None and asset.frame_index is not None:
            errors.append(f"{asset.role} cannot declare both anchor_time_ms and frame_index")
        for field_name, value in (("anchor_time_ms", asset.anchor_time_ms), ("frame_index", asset.frame_index)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                errors.append(f"{field_name} must be an integer when present")
        if asset.anchor_time_ms is not None and asset.anchor_time_ms < 0:
            errors.append("anchor_time_ms must not be negative")
        if asset.frame_index is not None and asset.frame_index < 0:
            errors.append("frame_index must not be negative")

    durations: dict[str, list[float]] = {"video": [], "audio": []}
    for asset in request.media:
        if asset.role not in ALL_ROLES:
            continue
        duration = _preflight_asset(asset, errors, warnings)
        if duration is not None and asset.kind in durations:
            durations[asset.kind].append(duration)
    for kind, values in durations.items():
        if sum(values) > 15.001:
            errors.append(f"total reference {kind} duration must not exceed 15 seconds")

    body_bytes: int | None = None
    if not errors:
        try:
            body_bytes = len(
                json.dumps(request.to_payload(encode_local=encode_local), separators=(",", ":")).encode(
                    "utf-8"
                )
            )
        except (OSError, H3InputError) as exc:
            errors.append(str(exc))
        else:
            if body_bytes > MAX_BODY_BYTES:
                errors.append("encoded request body exceeds 64 MB; use public URLs or mm_file:// IDs")
    return PreflightReport(tuple(errors), tuple(warnings), body_bytes)


def _is_remote(source: str) -> bool:
    parsed = urlparse(source)
    return parsed.scheme in {"http", "https"} or source.startswith("mm_file://")


def _preflight_asset(
    asset: MediaAsset, errors: list[str], warnings: list[str]
) -> float | None:
    source = asset.source.strip()
    if not source:
        errors.append(f"{asset.role} source must not be empty")
        return None
    if _is_remote(source):
        if source.startswith("http://"):
            warnings.append(f"{asset.role} uses an insecure public URL")
        warnings.append(f"{asset.role} remote media metadata was not verified locally")
        return None
    if source.startswith("data:"):
        try:
            raw = base64.b64decode(source.split(",", 1)[1], validate=True)
        except (IndexError, ValueError) as exc:
            errors.append(f"{asset.role} has an invalid data URI: {exc}")
            return None
        if len(raw) > MAX_BYTES[asset.kind]:
            errors.append(f"{asset.role} exceeds its {MAX_BYTES[asset.kind] // 1024 // 1024} MB limit")
        return None

    path = Path(source).expanduser().resolve()
    if not path.is_file():
        errors.append(f"media file does not exist: {path}")
        return None
    suffix = path.suffix.lower()
    if suffix not in EXTENSIONS[asset.kind]:
        errors.append(f"unsupported {asset.kind} extension for {asset.role}: {suffix or '(none)'}")
    size = path.stat().st_size
    if size > MAX_BYTES[asset.kind]:
        errors.append(f"{asset.role} exceeds its {MAX_BYTES[asset.kind] // 1024 // 1024} MB limit")
    if asset.kind == "image":
        dimensions = _image_dimensions(path)
        if dimensions is None:
            warnings.append(f"could not verify dimensions for {path.name}")
        else:
            width, height = dimensions
            if not 256 <= width <= 5760 or not 256 <= height <= 5760:
                errors.append(f"{asset.role} dimensions must be within 256-5760 px")
            ratio = width / height
            if not 0.4 <= ratio <= 2.5:
                errors.append(f"{asset.role} aspect ratio must be within 0.4-2.5")
    elif asset.kind in {"video", "audio"}:
        return _preflight_av(path, asset.kind, errors, warnings)
    return None


def _preflight_av(
    path: Path, kind: str, errors: list[str], warnings: list[str]
) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        warnings.append(f"ffprobe unavailable; duration/codec not verified for {path.name}")
        return None
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=15)
        metadata = json.loads(result.stdout)
        duration = float(metadata.get("format", {}).get("duration", 0))
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
        warnings.append(f"could not inspect {path.name}: {type(exc).__name__}")
        return None
    if not 2 <= duration <= 15:
        errors.append(f"{kind} reference duration must be within 2-15 seconds")
    streams = metadata.get("streams", [])
    if kind == "video":
        video_stream = next((item for item in streams if item.get("codec_type") == "video"), None)
        if not video_stream:
            errors.append(f"reference video has no video stream: {path.name}")
            return duration
        if video_stream.get("codec_name") not in {"h264", "hevc"}:
            errors.append("reference video codec must be H.264 or H.265/HEVC")
        width, height = int(video_stream.get("width", 0)), int(video_stream.get("height", 0))
        if width and height:
            if not 256 <= width <= 5760 or not 256 <= height <= 5760:
                errors.append("reference video dimensions must be within 256-5760 px")
            if not 0.4 <= width / height <= 2.5:
                errors.append("reference video aspect ratio must be within 0.4-2.5")
        fps = _parse_fps(str(video_stream.get("r_frame_rate", "0/1")))
        if fps and not 23.976 <= fps <= 60:
            errors.append("reference video frame rate must be within 23.976-60 FPS")
    return duration


def _parse_fps(value: str) -> float:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)", value)
    if not match:
        return 0.0
    denominator = float(match.group(2))
    return float(match.group(1)) / denominator if denominator else 0.0


def _image_dimensions(path: Path) -> tuple[int, int] | None:
    with path.open("rb") as handle:
        header = handle.read(32)
        if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
            return struct.unpack(">II", header[16:24])
        if header.startswith(b"\xff\xd8"):
            handle.seek(2)
            while True:
                marker_start = handle.read(1)
                if not marker_start:
                    return None
                if marker_start != b"\xff":
                    continue
                marker = handle.read(1)
                while marker == b"\xff":
                    marker = handle.read(1)
                if marker in {b"\xd8", b"\xd9"}:
                    continue
                length_bytes = handle.read(2)
                if len(length_bytes) != 2:
                    return None
                length = struct.unpack(">H", length_bytes)[0]
                if marker and marker[0] in range(0xC0, 0xC4):
                    segment = handle.read(5)
                    if len(segment) != 5:
                        return None
                    height, width = struct.unpack(">HH", segment[1:5])
                    return width, height
                handle.seek(max(0, length - 2), 1)
    return None


def _encode_source(asset: MediaAsset) -> str:
    if _is_remote(asset.source) or asset.source.startswith("data:"):
        return asset.source
    path = Path(asset.source).expanduser().resolve()
    mime = mimetypes.guess_type(path.name)[0] or {
        "image": "application/octet-stream",
        "video": "application/octet-stream",
        "audio": "application/octet-stream",
    }[asset.kind]
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
