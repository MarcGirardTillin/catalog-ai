"""Usage metering writes (M1).

`record_usage` inserts one append-only `usage_event` row; it deliberately does
NOT commit — the caller owns the transaction (pipeline/runner commits alongside
the work the usage belongs to, so events and results land atomically).
"""

from collections.abc import Mapping
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.models import UsageEvent


class TokenUsage(Protocol):
    """Any token-usage report (Claude client, import extraction contract)."""

    @property
    def model(self) -> str: ...
    @property
    def input_tokens(self) -> int: ...
    @property
    def output_tokens(self) -> int: ...


def record_usage(
    db: Session,
    *,
    account_id: int,
    source: str,
    provider: str,
    metric: str,
    quantity: int,
    job_id: int | None = None,
    item_id: int | None = None,
    model: str | None = None,
) -> UsageEvent:
    """Stage one usage event on the session (no commit — the caller commits)."""
    event = UsageEvent(
        account_id=account_id,
        job_id=job_id,
        item_id=item_id,
        source=source,
        provider=provider,
        model=model,
        metric=metric,
        quantity=quantity,
    )
    db.add(event)
    return event


def record_claude_usage(
    db: Session,
    *,
    account_id: int,
    usage: TokenUsage | Mapping[str, Any],
    source: str,
    job_id: int | None = None,
    item_id: int | None = None,
) -> None:
    """Record one Claude call: an input_tokens and an output_tokens event."""
    if isinstance(usage, Mapping):
        model = usage.get("model")
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
    else:
        model = usage.model
        input_tokens = int(usage.input_tokens)
        output_tokens = int(usage.output_tokens)
    for metric, quantity in (
        ("input_tokens", input_tokens),
        ("output_tokens", output_tokens),
    ):
        record_usage(
            db,
            account_id=account_id,
            source=source,
            provider="claude",
            metric=metric,
            quantity=quantity,
            job_id=job_id,
            item_id=item_id,
            model=model,
        )
