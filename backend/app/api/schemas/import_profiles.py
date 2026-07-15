"""Import profile schemas: the FROZEN rule shapes for supplier conventions.

Real-world references (everyday-tasks fixtures):
- L'Espion: price = wholesale x coefficient rounded UP to the nearest 5,
  constructed barcodes REF-COLOR-SIZE (PDFs carry no EAN), season label
  like "HIVER 2026", gender "Femme".
- Bambinoh (Garcia/LTDC/...): retail price as printed, real EANs, brand
  lowercased or as typed, season "H26", category left empty when not
  deducible.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

# How the CSV `price` column is computed:
# - "retail_as_is": the extracted retail_price, unchanged (Bambinoh).
# - "coefficient": wholesale_price x coefficient, rounded UP to the nearest
#   `round_up_to` euros (L'Espion: coefficient given per order, round to 5).
PriceMode = Literal["retail_as_is", "coefficient"]

# How the CSV `variant_barcode` column is filled:
# - "ean": the extracted EAN (skipped when absent).
# - "constructed": REF-COLOR-SIZE built from the resolved values (L'Espion).
BarcodeMode = Literal["ean", "constructed"]

# How the CSV `brand` column is filled:
# - "as_extracted": the (possibly review-edited) extracted brand.
# - "fixed": always `brand_value` (Bambinoh: supplier folder name, lowercase).
BrandMode = Literal["as_extracted", "fixed"]


class ImportProfileConfig(BaseModel):
    """Frozen convention shapes; every field has a safe default."""

    price_mode: PriceMode = "retail_as_is"
    coefficient: Decimal | None = None  # required when price_mode="coefficient"
    round_up_to: Decimal = Decimal(5)  # rounding step for coefficient mode

    barcode_mode: BarcodeMode = "ean"

    brand_mode: BrandMode = "as_extracted"
    brand_value: str = ""  # used when brand_mode="fixed"

    supplier_label: str = ""  # CSV `supplier` column ("" = extracted supplier)
    season_label: str = ""  # CSV `season` column ("" = extracted season)
    tax_rate: str = "20"  # CSV `tax_rate` column (VAT on the sale price)
    # CSV `wholesale_tax_rate` column (tax on the purchase price) — "0" for a
    # foreign supplier (no input VAT), "20" for a domestic one.
    wholesale_tax_rate: str = "20"
    status: str = "active"  # CSV `status` column
    # When True, the CSV `title` column is rendered from the account's title
    # template (settings) instead of the raw extracted title. Off by default:
    # most imports keep the supplier's title and only template at enrichment.
    apply_title_template: bool = False
    # When True, a document product carrying SEVERAL colors is split into one
    # sheet per color AT EXTRACTION TIME (reference suffixed by the color for
    # Tillin uniqueness). Off by default: colors stay variants of one product.
    # Applied when the products are staged — attaching the profile after the
    # extraction does not re-split already staged items.
    split_by_color: bool = False
    # NOTE: gender/category defaults were removed on user request (2026-07-09):
    # those are per-product review-grid edits, not supplier conventions.
    # Stored configs may still carry the old keys — pydantic ignores them.


class ImportProfilePublic(BaseModel):
    id: int
    name: str
    supplier_match: str
    config: ImportProfileConfig
    created_at: datetime
    updated_at: datetime


class ImportProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    supplier_match: str = Field(default="", max_length=120)
    config: ImportProfileConfig = Field(default_factory=ImportProfileConfig)


class ImportProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    supplier_match: str | None = Field(default=None, max_length=120)
    config: ImportProfileConfig | None = None


class ImportProfilesBulkUpdate(BaseModel):
    """Harmonize the catalogue-wide conventions across several profiles.

    Only the fields that behave the same for the whole catalogue are
    bulk-editable; None = leave that field untouched on every profile.
    """

    profile_ids: list[int] = Field(min_length=1)
    season_label: str | None = None
    apply_title_template: bool | None = None
    split_by_color: bool | None = None
