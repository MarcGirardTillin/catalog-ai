"""Settings schemas: per-user UI preferences and account-level defaults."""

from typing import Literal

from pydantic import BaseModel, Field


class UserPreferences(BaseModel):
    """Per-user UI preferences (stored on user.preferences_json).

    Unknown keys in storage are ignored; missing keys take these defaults.
    """

    # Review keyboard shortcuts (V/R/A + arrows). Off by default.
    shortcuts_enabled: bool = False
    # After a review decision, jump to the job's next reviewable item.
    auto_advance: bool = True
    density: Literal["comfortable", "compact"] = "comfortable"
    products_per_page: int = Field(20, ge=10, le=100)


class AccountSettings(BaseModel):
    """Boutique-level enrichment defaults (stored on account.settings_json)."""

    # Default title template for new jobs ({brand}/{title}/{season}/{color}…).
    title_template: str | None = None
    # Default editorial instructions handed to the copywriter for new jobs.
    editorial_instructions: str | None = None
    # Boutique context (markdown) prefixed to the copywriter's instructions.
    client_context: str | None = None
    # Soft SEO limit surfaced by the meta counter in review.
    meta_max_length: int = Field(160, ge=50, le=320)
    # Notifications (UI placeholder until the Brevo integration lands).
    notify_on_job_done: bool = False
    notify_email: str | None = None
    # Billing markup applied at read time: billable = cost × coefficient.
    billing_coefficient: float = Field(1.0, ge=0)


class ConnectionStatus(BaseModel):
    """Read-only Tillin/Xano connection health (no secrets)."""

    configured: bool
    host: str | None = None
    data_source: str | None = None
