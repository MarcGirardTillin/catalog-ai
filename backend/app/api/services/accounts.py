"""Account helpers — one CatalogAI account per Tillin company.

The company comes from Xano's `/auth/me` at login. The historical default
account (NULL company) remains the home of app-local users (operator, dev):
they never authenticated against Xano, so no company can be inferred.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, User
from app.models.account import DEFAULT_ACCOUNT_NAME
from app.models.usage_price import UsagePrice

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


def _placeholder_name(company_id: int) -> str:
    return f"Entreprise {company_id}"


def _name_is_free(db: Session, name: str, *, except_id: int | None = None) -> bool:
    other = db.scalar(select(Account).where(Account.name == name))
    return other is None or other.id == except_id


def get_or_create_company_account(
    db: Session, company_id: int, *, company_name: str | None = None
) -> Account:
    """The account bound to a Tillin company, created on first login.

    Named after the company (`company_all_informations.name`, fetched with the
    user's fresh token) ; placeholder `Entreprise {id}` when unavailable —
    upgraded to the real name at the next login that carries it. The operator
    pricing policy is seeded from the oldest account: the global
    PUT /admin/settings keeps every account in sync, so any of them reflects
    the current policy (looking one up BY NAME would recreate ghost accounts).
    """
    wanted = (company_name or "").strip() or None
    account = db.scalar(select(Account).where(Account.xano_company_id == company_id))
    if account is not None:
        if (
            wanted
            and account.name != wanted
            and account.name == _placeholder_name(company_id)
            and _name_is_free(db, wanted, except_id=account.id)
        ):
            account.name = wanted
            db.commit()
        return account
    seed_source = db.scalar(select(Account).order_by(Account.id).limit(1))
    seeded = {
        key: value
        for key, value in (
            (seed_source.settings_json if seed_source else None) or {}
        ).items()
        if key in OPERATOR_SEEDED_KEYS
    }
    name = (
        wanted
        if wanted and _name_is_free(db, wanted)
        else _placeholder_name(company_id)
    )
    account = Account(
        name=name,
        xano_company_id=company_id,
        settings_json=seeded or None,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    _seed_usage_prices(db, seed_source, account)
    return account


def _seed_usage_prices(
    db: Session, seed_source: Account | None, account: Account
) -> None:
    """Copy the € cost grid (`usage_price`) onto a freshly created account.

    `usage_price` is a separate table (not `settings_json`), so it was left
    out of `OPERATOR_SEEDED_KEYS` and a new company account got NO price rows
    at all — the admin usage screen then reports the grid as missing (seen
    live for the JoggingJogging account). Same source-of-truth rule as the
    settings seed: the oldest account, kept current by every operator write.
    """
    if seed_source is None:
        return
    prices = db.scalars(
        select(UsagePrice).where(UsagePrice.account_id == seed_source.id)
    ).all()
    for price in prices:
        db.add(
            UsagePrice(
                account_id=account.id,
                provider=price.provider,
                model=price.model,
                metric=price.metric,
                unit_price=price.unit_price,
                currency=price.currency,
            )
        )
    if prices:
        db.commit()


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
