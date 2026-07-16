"""Settings schemas: per-user UI preferences and account-level defaults."""

from typing import Literal

from pydantic import BaseModel, Field

from app.api.schemas.imaging import FormatOption, RatioOption

# How the rendered title is cased: left as-is, UPPER CASE, Capitalized
# (first letters raised, rest untouched — preserves acronyms/brand styling),
# or strict Title Case (first letters raised, REST LOWERED — "ARMEDANGELS"
# becomes "Armedangels", but so does "XL" → "Xl": the trade-off is the
# user's, per account).
TitleCase = Literal["none", "upper", "capitalize", "title"]


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


class CreditPack(BaseModel):
    """One purchasable credit pack shown on the client usage page."""

    credits: int = Field(ge=1)
    price_eur: float = Field(ge=0)


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
    # --- Crédits prépayés (grille par action, admin-only) : 1 crédit = la
    # valeur faciale vendue au client ; le solde décrémente à chaque action
    # et les lancements sont refusés (402) à solde insuffisant. ---
    credit_cost_import_product: int = Field(1, ge=0)
    credit_cost_enrich_item: int = Field(2, ge=0)
    credit_cost_image_process: int = Field(1, ge=0)
    credit_cost_image_generate: int = Field(5, ge=0)
    # Free credits granted once per month (subscription perk); 0 = none.
    monthly_free_credits: int = Field(0, ge=0)
    # Below this balance the client UI shows a low-credit warning.
    low_credit_threshold: int = Field(50, ge=0)
    # Purchasable packs shown to the client (bookkeeping stays manual).
    credit_packs: list[CreditPack] = Field(default_factory=list)
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
    # --- Génération de visuels (porté mannequin) : traduits en instruction
    # (prompt) à chaque génération ; surchargables au lancement (studio). ---
    imaging_generation_framing: Literal["full_body", "cropped_head"] = "full_body"
    imaging_generation_scene: Literal["studio", "lifestyle"] = "studio"
    imaging_generation_instructions: str | None = None


class OperatorSettings(BaseModel):
    """Operator-owned settings managed GLOBALLY (admin console, one form).

    Written to every account so per-account values never diverge — the app is
    single-tenant today, and the pricing/consumption policy is the operator's,
    not the client's. The legacy billing_coefficient is deliberately absent
    (superseded by the credit model; it stays at its stored value).
    """

    minutes_saved_per_import_product: int = Field(2, ge=0, le=120)
    minutes_saved_per_enriched_product: int = Field(10, ge=0, le=120)
    billing_day: int = Field(1, ge=1, le=28)
    credit_cost_import_product: int = Field(1, ge=0)
    credit_cost_enrich_item: int = Field(2, ge=0)
    credit_cost_image_process: int = Field(1, ge=0)
    credit_cost_image_generate: int = Field(5, ge=0)
    monthly_free_credits: int = Field(0, ge=0)
    low_credit_threshold: int = Field(50, ge=0)
    credit_packs: list[CreditPack] = Field(default_factory=list)


class ConnectionStatus(BaseModel):
    """Read-only Tillin/Xano connection health (no secrets)."""

    configured: bool
    host: str | None = None
    data_source: str | None = None
