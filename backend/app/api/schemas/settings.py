"""Settings schemas: per-user UI preferences and account-level defaults."""

from typing import Literal

from pydantic import BaseModel, Field

from app.api.schemas.imaging import FormatOption, RatioOption

# How the rendered title is cased: left as-is, UPPER CASE, or Capitalized.
TitleCase = Literal["none", "upper", "capitalize"]


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
    # Casing applied to the rendered title (none | upper | capitalize).
    title_case: TitleCase = "none"
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
    # « Temps gagné » shown on the client dashboard: minutes saved per product
    # sheet created by an import transfer, and per sheet enriched (applied).
    # Admin-managed (PUT /admin/accounts/{id}/settings) — the client-facing
    # settings PUT preserves the stored values.
    minutes_saved_per_import_product: int = Field(2, ge=0, le=120)
    minutes_saved_per_enriched_product: int = Field(10, ge=0, le=120)
    # Day of the month a period is billed on: a month is billed (and its
    # prices frozen) on this day of the FOLLOWING month. 1 = frozen as soon
    # as the month rolls over.
    billing_day: int = Field(1, ge=1, le=28)
    # --- Imaging: the boutique's normalization defaults (à la carte) ---
    imaging_remove_bg: bool = True
    imaging_bg_color: str = Field("FFFFFF", pattern=r"^#?[0-9a-fA-F]{6}$")
    imaging_ratio: RatioOption = "4:5"
    imaging_center: bool = True
    imaging_format: FormatOption = "webp"
    imaging_quality: int = Field(80, ge=1, le=100)
    imaging_max_kb: int = Field(300, ge=1, le=5000)
    # Image filename template ({reference}/{color}/{position}/{brand}/{title}),
    # rendered then slugged at save time; None = default technical names.
    image_title_template: str | None = None


class ConnectionStatus(BaseModel):
    """Read-only Tillin/Xano connection health (no secrets)."""

    configured: bool
    host: str | None = None
    data_source: str | None = None
