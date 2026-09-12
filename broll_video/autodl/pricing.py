"""Small AutoDL continuous-billing quote catalog."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import json
from pathlib import Path
from typing import Mapping


class AutoDLPricingError(ValueError):
    pass


@dataclass(frozen=True)
class AutoDLPricingCatalog:
    hourly_rate_cny: Decimal
    valid_until: datetime
    profile_seconds: Mapping[str, int]
    rate_source: str = "cached_offline_estimate"

    @classmethod
    def load(cls, path: Path | str, *, now: datetime | None = None) -> "AutoDLPricingCatalog":
        try:
            payload = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AutoDLPricingError("AutoDL pricing config is unreadable") from exc
        if payload.get("provider") != "autodl" or payload.get("currency") != "CNY":
            raise AutoDLPricingError("AutoDL pricing config provider/currency is invalid")
        try:
            rate = Decimal(str(payload["hourly_rate_cny"]))
            until = datetime.fromisoformat(str(payload["valid_until"]).replace("Z", "+00:00"))
            seconds = {str(key): int(value) for key, value in dict(payload["profile_reserved_seconds"]).items()}
        except (KeyError, TypeError, ValueError) as exc:
            raise AutoDLPricingError("AutoDL pricing config fields are invalid") from exc
        if until.tzinfo is None or rate <= 0 or not seconds or any(value <= 0 for value in seconds.values()):
            raise AutoDLPricingError("AutoDL pricing config values are invalid")
        return cls(rate, until.astimezone(timezone.utc), seconds)

    def with_live_payg_milli(self, value: object) -> "AutoDLPricingCatalog":
        """Replace the cached planning rate with the authenticated live platform rate."""

        try:
            milli = int(value)
        except (TypeError, ValueError) as exc:
            raise AutoDLPricingError("AutoDL live payg price is invalid") from exc
        if isinstance(value, bool) or milli <= 0:
            raise AutoDLPricingError("AutoDL live payg price is invalid")
        return AutoDLPricingCatalog(
            Decimal(milli) / Decimal(1000),
            self.valid_until,
            self.profile_seconds,
            f"authenticated_snapshot_payg:{milli}",
        )

    def quote(self, profile: str) -> Decimal:
        if profile not in self.profile_seconds:
            raise AutoDLPricingError("AutoDL profile has no conservative quote")
        return (self.hourly_rate_cny * Decimal(self.profile_seconds[profile]) / Decimal(3600)).quantize(Decimal("0.01"), rounding=ROUND_CEILING)

    # The orchestration layer consumes this deliberately small pricing duck
    # interface.  AutoDL bills continuously, so startup is reserved once per
    # plan and each profile reserves its conservative runtime window.
    @property
    def source_reference(self) -> str:
        return self.rate_source

    @property
    def catalog_version(self) -> str:
        return f"{self.rate_source}:{self.hourly_rate_cny}"

    def require_current(self) -> None:
        # The file is a conservative offline estimate. A live run replaces its
        # rate from the authenticated snapshot before any submission.
        return None

    def quote_startup(self) -> Decimal:
        return Decimal("0.00")

    def quote_request(self, request: object) -> Decimal:
        return self.quote(str(getattr(request, "provider_profile", "")))

    def verify_live_rate(self, value: object) -> None:
        # Service clients expose CNY/hour, while AutoDL snapshot exposes milli
        # CNY/hour.  Control attestation has already checked the latter.
        if Decimal(str(value)) != self.hourly_rate_cny:
            raise AutoDLPricingError("AutoDL live hourly rate differs from audited pricing")

    def validate_rtx_canary(self, resolution: str, report: object) -> None:
        if resolution != "4K":
            return
        if not isinstance(report, dict) or report.get("passed") is not True:
            raise AutoDLPricingError("AutoDL 4K quote requires a passed offline RTX graph canary")
        if report.get("applicable") is not True or report.get("fps") != 24:
            raise AutoDLPricingError("AutoDL 4K RTX graph canary has the wrong frame contract")
