"""Paid-request authorization boundary for H3.

The runtime cannot know current provider pricing reliably. Callers must supply a
quote and the B-roll task ledger state. This is intentionally fail-closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


MAX_UNATTENDED_CNY = Decimal("20.00")


class BudgetError(ValueError):
    """Raised when a paid request lacks safe budget authorization."""


def _money(value: object, field: str) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise BudgetError(f"{field} must be a valid CNY amount") from exc
    if amount < 0:
        raise BudgetError(f"{field} must not be negative")
    return amount


@dataclass(frozen=True)
class BudgetAuthorization:
    """A one-request budget quote backed by the B-roll task ledger."""

    hard_limit_cny: object
    spent_cny: object
    committed_cny: object
    estimated_cost_cny: object
    approved: bool
    quote_source: str
    ledger_reservation_id: str = ""
    request_fingerprint: str = ""

    def validate(self, expected_fingerprint: str | None = None) -> Decimal:
        if not self.approved:
            raise BudgetError("paid H3 request is not approved")
        if not self.quote_source.strip():
            raise BudgetError("paid H3 request requires a quote source")
        if not self.ledger_reservation_id.strip():
            raise BudgetError("task ledger must durably reserve this request before submission")
        if expected_fingerprint is not None:
            if not self.request_fingerprint.strip() or self.request_fingerprint != expected_fingerprint:
                raise BudgetError("task ledger reservation does not match the H3 request fingerprint")
        limit = _money(self.hard_limit_cny, "hard_limit_cny")
        spent = _money(self.spent_cny, "spent_cny")
        committed = _money(
            self.committed_cny,
            "committed_cny (including this request)",
        )
        estimate = _money(self.estimated_cost_cny, "estimated_cost_cny")
        if limit > MAX_UNATTENDED_CNY:
            raise BudgetError("unattended task hard limit cannot exceed 20.00 CNY")
        if estimate == 0:
            raise BudgetError("paid H3 request requires a non-zero cost estimate")
        if committed < estimate:
            raise BudgetError("ledger committed amount does not include this request estimate")
        if spent + committed > limit:
            remaining = limit - spent
            raise BudgetError(
                f"ledger exceeds budget after reservation: committed {committed:.2f} CNY, "
                f"available after spend {remaining:.2f} CNY"
            )
        return estimate
