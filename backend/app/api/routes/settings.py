"""Settings routes: user preferences, account defaults, connection status."""

from urllib.parse import urlparse

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, SessionDep
from app.api.schemas.settings import (
    AccountSettings,
    ConnectionStatus,
    UserPreferences,
)
from app.api.services.accounts import resolve_account_id
from app.core.config import settings as app_settings
from app.models import Account

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/me", response_model=UserPreferences)
def read_my_preferences(current_user: CurrentUserDep) -> UserPreferences:
    """The signed-in user's UI preferences (defaults filled in)."""
    return UserPreferences.model_validate(current_user.preferences_json or {})


@router.put("/me", response_model=UserPreferences)
def update_my_preferences(
    payload: UserPreferences, db: SessionDep, current_user: CurrentUserDep
) -> UserPreferences:
    current_user.preferences_json = payload.model_dump()
    db.commit()
    return payload


@router.get("/account", response_model=AccountSettings)
def read_account_settings(
    db: SessionDep, current_user: CurrentUserDep
) -> AccountSettings:
    """The account's enrichment defaults (defaults filled in)."""
    account_id = resolve_account_id(db, current_user)
    account = db.get(Account, account_id)
    return AccountSettings.model_validate(
        (account.settings_json if account else None) or {}
    )


# Operator-owned settings a client user must not be able to change through
# the public settings PUT (billing margin, dashboard time-saved rates). They
# are managed via /admin/accounts/{id}/settings.
ADMIN_ONLY_SETTINGS = (
    "billing_coefficient",
    "minutes_saved_per_import_product",
    "minutes_saved_per_enriched_product",
    # Jour de facturation : politique opérateur globale (Admin > Tarification),
    # plus éditable depuis les paramètres du client (2026-07-16).
    "billing_day",
    # Modules souscrits : un client ne s'auto-attribue pas un module.
    "feature_import",
    "feature_enrich",
    "feature_studio",
    "credit_cost_import_product",
    "credit_cost_enrich_item",
    "credit_cost_image_process",
    "credit_cost_image_generate",
    "monthly_free_credits",
    "low_credit_threshold",
    "credit_packs",
)


@router.put("/account", response_model=AccountSettings)
def update_account_settings(
    payload: AccountSettings, db: SessionDep, current_user: CurrentUserDep
) -> AccountSettings:
    account_id = resolve_account_id(db, current_user)
    account = db.get(Account, account_id)
    if account is None:
        return payload
    if not current_user.is_admin:
        # Preserve operator-owned fields whatever the client sent.
        stored = AccountSettings.model_validate(account.settings_json or {})
        for name in ADMIN_ONLY_SETTINGS:
            setattr(payload, name, getattr(stored, name))
    account.settings_json = payload.model_dump()
    db.commit()
    return payload


@router.get("/connection", response_model=ConnectionStatus)
def read_connection_status(_current_user: CurrentUserDep) -> ConnectionStatus:
    """Whether the Tillin/Xano integration is configured (never any secret)."""
    if not app_settings.xano_configured:
        return ConnectionStatus(configured=False)
    return ConnectionStatus(
        configured=True,
        host=urlparse(app_settings.XANO_BASE_URL).hostname,
        data_source=app_settings.XANO_DATA_SOURCE or "production",
    )
