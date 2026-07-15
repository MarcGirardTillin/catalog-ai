"""API-test defaults: a comfortable credit balance on the default account.

The prepaid-credit guards (402 insufficient_credits) block every launch route
at balance 0, which is the natural state of a fresh test database. Route tests
are about their own feature, not about credits — so each one starts with a
large float. `test_credits.py` opts out (it is precisely about balances and
guards).
"""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.api.services.accounts import get_or_create_default_account
from app.models import CreditEntry


@pytest.fixture(autouse=True)
def _credit_float(
    request: pytest.FixtureRequest,
) -> Generator[None]:
    if request.node.path.name == "test_credits.py":
        yield
        return
    if "db_session_factory" not in request.fixturenames:
        yield
        return
    factory: sessionmaker[Session] = request.getfixturevalue("db_session_factory")
    db = factory()
    try:
        account = get_or_create_default_account(db)
        db.add(
            CreditEntry(
                account_id=account.id,
                kind="grant",
                credits=1_000_000,
                label="test float",
            )
        )
        db.commit()
    finally:
        db.close()
    yield
