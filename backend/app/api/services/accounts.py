"""Account helpers — one CatalogAI account per Tillin company.

The company comes from Xano's `/auth/me` at login. The historical default
account (NULL company) remains the home of app-local users (operator, dev):
they never authenticated against Xano, so no company can be inferred.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, User
from app.models.account import DEFAULT_ACCOUNT_NAME

# Operator-owned pricing/consumption policy is written to EVERY account by
# PUT /admin/settings. A company account created AFTER such a write must not
# silently fall back to code defaults: seed these keys from the default
# account, which the global write always keeps current.
OPERATOR_SEEDED_KEYS = (
    "billing_coefficient",
    "minutes_saved_per_import_product",
    "minutes_saved_per_enriched_product",
    "billing_day",
    "credit_cost_import_product",
    "credit_cost_enrich_item",
    "credit_cost_image_process",
    "credit_cost_image_generate",
    "monthly_free_credits",
    "low_credit_threshold",
    "credit_packs",
)


def get_or_create_default_account(db: Session) -> Account:
    account = db.scalar(select(Account).where(Account.name == DEFAULT_ACCOUNT_NAME))
    if account is None:
        account = Account(name=DEFAULT_ACCOUNT_NAME)
        db.add(account)
        db.commit()
        db.refresh(account)
    return account


def get_or_create_company_account(db: Session, company_id: int) -> Account:
    """The account bound to a Tillin company, created on first login.

    The name is a placeholder (`Entreprise {id}`) — Xano's `/auth/me` exposes
    only the numeric company id; the operator can recognize accounts by their
    users in the admin console.
    """
    account = db.scalar(select(Account).where(Account.xano_company_id == company_id))
    if account is not None:
        return account
    default = get_or_create_default_account(db)
    seeded = {
        key: value
        for key, value in (default.settings_json or {}).items()
        if key in OPERATOR_SEEDED_KEYS
    }
    account = Account(
        name=f"Entreprise {company_id}",
        xano_company_id=company_id,
        settings_json=seeded or None,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def resolve_account_id(db: Session, user: User) -> int:
    """The user's account, falling back to (and backfilling) the default one.

    Xano-authenticated users are attached to their company account at login;
    this fallback only concerns app-local users (operator/dev).
    """
    if user.account_id is not None:
        return user.account_id
    account = get_or_create_default_account(db)
    user.account_id = account.id
    db.commit()
    return account.id


def freshest_company_token(db: Session, account_id: int) -> str | None:
    """The most recently captured Xano token among the account's active users.

    Any user of the account works: Xano scopes calls to the COMPANY carried by
    the token, and all the account's users belong to that company. Taking the
    freshest one maximizes remaining lifetime (72h TTL), and lets a colleague's
    recent login keep background jobs running after the launcher's expired.
    """
    return db.scalar(
        select(User.xano_token)
        .where(
            User.account_id == account_id,
            User.is_active.is_(True),
            User.xano_token.is_not(None),
        )
        .order_by(User.xano_token_at.desc())
        .limit(1)
    )
