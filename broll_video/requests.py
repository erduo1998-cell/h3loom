"""Canonical H3 request files for approved B-roll storyboards."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .h3 import H3Request, MediaAsset, preflight_request


def _assets_from_payload(payload: Mapping[str, Any]) -> tuple[MediaAsset, ...]:
    """Accept legacy ``media`` and the immutable reference-manifest envelope.

    Old request/provider records only contain ``media``.  New records may also
    carry ``reference_manifest.assets``; when both are present they must be the
    same ordered contract, so an approval cannot be bypassed by editing only one
    representation.
    """
    raw_media = payload.get("media", [])
    manifest = payload.get("reference_manifest")
    if manifest is not None:
        if not isinstance(manifest, Mapping) or manifest.get("schema_version") != "1.0":
            raise ValueError("reference_manifest must be a schema_version 1.0 object")
        raw_manifest = manifest.get("assets")
        if not isinstance(raw_manifest, list):
            raise ValueError("reference_manifest.assets must be an array")
        if "media" in payload and raw_media != raw_manifest:
            raise ValueError("media and reference_manifest.assets must be identical and ordered")
        raw_media = raw_manifest
    if not isinstance(raw_media, list):
        raise ValueError("media must be an array")

    assets: list[MediaAsset] = []
    for item in raw_media:
        if not isinstance(item, Mapping):
            raise ValueError("each media/reference manifest entry must be an object")
        for field_name in ("must_preserve", "may_change", "used_by"):
            value = item.get(field_name, [])
            if not isinstance(value, list) or not all(isinstance(part, str) for part in value):
                raise ValueError(f"{field_name} must be an array of strings")
        assets.append(
            MediaAsset(
                source=str(item["source"]),
                role=str(item.get("role", "reference_image")),
                source_origin=_optional_string(item, "source_origin"),
                rights_note=_optional_string(item, "rights_note"),
                semantic_role=_optional_string(item, "semantic_role"),
                must_preserve=tuple(item.get("must_preserve", [])),
                may_change=tuple(item.get("may_change", [])),
                used_by=tuple(item.get("used_by", [])),
                prompt_label=_optional_string(item, "prompt_label"),
                anchor_time_ms=item.get("anchor_time_ms"),
                frame_index=item.get("frame_index"),
            )
        )
    return tuple(assets)


def _optional_string(item: Mapping[str, Any], name: str) -> str | None:
    value = item.get(name)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{name} must be a string when present")
    return value


def request_from_dict(payload: Mapping[str, Any]) -> H3Request:
    media = _assets_from_payload(payload)
    request = H3Request(
        prompt=str(payload.get("prompt", "")),
        duration=payload.get("duration"),
        ratio=str(payload.get("ratio", "")),
        resolution=str(payload.get("resolution", "4K")),
        media=media,
        provider_profile=str(payload.get("provider_profile", "fast")),
        seed=payload.get("seed"),
        audio_policy=str(payload.get("audio_policy", "sfx_only")),
        refine_pass2_model=_optional_string(payload, "refine_pass2_model"),
        refine_pass2_steps=payload.get("refine_pass2_steps"),
        refine_pass2_denoise=payload.get("refine_pass2_denoise"),
        refine_pass2_scale=payload.get("refine_pass2_scale"),
        experimental_canary=payload.get("experimental_canary", False),
        production_contract=_optional_string(payload, "production_contract"),
    )
    preflight_request(request, encode_local=False).require_ok()
    return request


def load_request(path: Path | str, *, expected_provider: str | None = None) -> H3Request:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"H3 request must be a JSON object: {target}")
    provider = payload.get("provider")
    if provider is not None and provider != "autodl":
        raise ValueError("request provider must be autodl")
    if expected_provider == "autodl" and provider != "autodl":
        raise ValueError("new AutoDL requests must explicitly bind provider=autodl")
    if expected_provider is not None and provider is not None and provider != expected_provider:
        raise ValueError("request provider differs from task authority")
    return request_from_dict(payload)


def request_to_dict(request: H3Request, *, provider: str | None = None) -> dict[str, Any]:
    if provider is not None and provider != "autodl":
        raise ValueError("request provider must be autodl")
    assets = [_asset_to_dict(item) for item in request.media]
    payload: dict[str, Any] = {
        "prompt": request.prompt,
        "duration": request.duration,
        "ratio": request.ratio,
        "resolution": request.resolution,
        "provider_profile": request.provider_profile,
        "seed": request.seed,
        "audio_policy": request.audio_policy,
        # Retain ``media`` for historical tooling; the manifest is the versioned
        # authority for newly written request files and is compared on load.
        "media": assets,
        "reference_manifest": {"schema_version": "1.0", "assets": assets},
    }
    if request.production_contract is not None:
        payload["production_contract"] = request.production_contract
    for field_name in (
        "refine_pass2_model",
        "refine_pass2_steps",
        "refine_pass2_denoise",
        "refine_pass2_scale",
    ):
        value = getattr(request, field_name)
        if value is not None:
            payload[field_name] = value
    if request.experimental_canary:
        payload["experimental_canary"] = True
    if provider is not None:
        payload["provider"] = provider
    return payload


def _asset_to_dict(item: MediaAsset) -> dict[str, Any]:
    payload: dict[str, Any] = {"source": item.source, "role": item.role}
    for field_name in (
        "source_origin",
        "rights_note",
        "semantic_role",
        "prompt_label",
        "anchor_time_ms",
        "frame_index",
    ):
        value = getattr(item, field_name)
        if value is not None:
            payload[field_name] = value
    for field_name in ("must_preserve", "may_change", "used_by"):
        value = getattr(item, field_name)
        if value:
            payload[field_name] = list(value)
    return payload
