"""Tests for the usage metering writes (M1)."""

from sqlalchemy.orm import Session, sessionmaker

from app.api.services.usage import record_claude_usage, record_usage
from app.clients.claude import ClaudeUsage
from app.models import Account, UsageEvent


def _seed_account(db: Session) -> int:
    account = Account(name="default")
    db.add(account)
    db.commit()
    return account.id


def test_record_usage_stages_one_event_without_committing(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    account_id = _seed_account(db)

    record_usage(
        db,
        account_id=account_id,
        source="import",
        provider="claude",
        metric="input_tokens",
        quantity=1234,
        job_id=None,
        model="claude-test-1",
    )
    # The caller owns the transaction: nothing visible until it commits.
    db.rollback()
    assert db.query(UsageEvent).count() == 0

    record_usage(
        db,
        account_id=account_id,
        source="import",
        provider="claude",
        metric="input_tokens",
        quantity=1234,
        model="claude-test-1",
    )
    db.commit()
    event = db.query(UsageEvent).one()
    assert (event.source, event.provider, event.metric) == (
        "import",
        "claude",
        "input_tokens",
    )
    assert event.quantity == 1234
    assert event.model == "claude-test-1"
    assert event.job_id is None
    assert event.item_id is None
    db.close()


def test_record_claude_usage_writes_input_and_output_events(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    account_id = _seed_account(db)

    usage = ClaudeUsage(model="claude-test-1", input_tokens=900, output_tokens=150)
    record_claude_usage(
        db, account_id=account_id, usage=usage, source="enrichment", job_id=7, item_id=3
    )
    db.commit()

    events = db.query(UsageEvent).order_by(UsageEvent.id).all()
    assert [(e.metric, e.quantity) for e in events] == [
        ("input_tokens", 900),
        ("output_tokens", 150),
    ]
    assert all(
        (e.account_id, e.source, e.provider, e.model, e.job_id, e.item_id)
        == (account_id, "enrichment", "claude", "claude-test-1", 7, 3)
        for e in events
    )
    db.close()


def test_record_claude_usage_accepts_a_plain_dict(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    account_id = _seed_account(db)

    record_claude_usage(
        db,
        account_id=account_id,
        usage={"model": "claude-test-1", "input_tokens": 10, "output_tokens": 2},
        source="import",
    )
    db.commit()

    events = db.query(UsageEvent).order_by(UsageEvent.id).all()
    assert [(e.metric, e.quantity) for e in events] == [
        ("input_tokens", 10),
        ("output_tokens", 2),
    ]
    db.close()
