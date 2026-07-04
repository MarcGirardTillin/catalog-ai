"""Account helpers (single-tenant: one default account)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, User
from app.models.account import DEFAULT_ACCOUNT_NAME


def get_or_create_default_account(db: Session) -> Account:
    account = db.scalar(select(Account).where(Account.name == DEFAULT_ACCOUNT_NAME))
    if account is None:
        account = Account(name=DEFAULT_ACCOUNT_NAME)
        db.add(account)
        db.commit()
        db.refresh(account)
    return account


def resolve_account_id(db: Session, user: User) -> int:
    """The user's account, falling back to (and backfilling) the default one."""
    if user.account_id is not None:
        return user.account_id
    account = get_or_create_default_account(db)
    user.account_id = account.id
    db.commit()
    return account.id
