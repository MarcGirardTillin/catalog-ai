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
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

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

# Conversion des pointures au RENDU Tillin (les valeurs extraites restent
# intactes) : grilles standard adulte, genre du produit pris en compte.
# ⚠ approximation assumée — les grilles varient selon les marques ; la
# conversion est visible dans l'aperçu CSV avant transfert.
SizeConversion = Literal["none", "uk_to_eu", "us_to_eu"]

# Champ de variante extrait alimentant un axe d'option Tillin :
# color/size = les deux axes classiques, extra = la troisième dimension
# (bonnet, longueur de jambe, largeur…) extraite quand le document la porte.
OptionSource = Literal["color", "size", "extra"]


class OptionAxis(BaseModel):
    """Un axe d'option du CSV Tillin : champ source + libellé affiché."""

    source: OptionSource
    label: str = Field(min_length=1, max_length=40)


def _default_option_axes() -> list[OptionAxis]:
    return [
        OptionAxis(source="color", label="Couleur"),
        OptionAxis(source="size", label="Taille"),
    ]


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
    # Axes de variantes du CSV Tillin (option1..option3), dans l'ORDRE du
    # rendu (demande Marc 2026-07-29 : ordre modifiable, 3e option possible,
    # 2 par défaut). La plupart des boutiques : Couleur puis Taille ; la
    # lingerie peut en vouloir 3 (Couleur, Tour de dos, Bonnet). Les valeurs
    # extraites restent color/size/extra ; seuls l'ordre et les LIBELLÉS
    # Tillin sont pilotés ici.
    option_axes: list[OptionAxis] = Field(
        default_factory=_default_option_axes, min_length=1, max_length=3
    )
    # Pointures UK/US converties en EU au rendu (chaussures) — "none" défaut.
    size_conversion: SizeConversion = "none"
    # Instructions d'extraction ENREGISTRÉES sur le profil (demande Marc
    # 2026-07-30) : injectées dans le prompt d'analyse quand le profil est
    # choisi au dépôt, cumulées avec les consignes saisies pour l'import.
    # Un profil auto-rattaché APRÈS extraction n'influence pas le prompt.
    extra_instructions: str = Field(default="", max_length=4000)
    # Genre appliqué quand le document n'en porte pas ("" = aucun repli).
    # Réintroduit sur demande Marc 2026-07-28 (retiré 2026-07-09) : REPLI
    # seulement — un genre extrait ou édité en review garde toujours la main.
    default_gender: str = Field(default="", max_length=40)
    # NOTE: the category default stays removed (2026-07-09): that one is a
    # per-product review-grid edit, not a supplier convention.
    # Stored configs may still carry the old keys — pydantic ignores them.

    @model_validator(mode="before")
    @classmethod
    def _legacy_option_names(cls, data: Any) -> Any:
        """Configs stockées avant `option_axes` : color/size_option_name."""
        if isinstance(data, dict) and "option_axes" not in data:
            legacy_color = data.get("color_option_name")
            legacy_size = data.get("size_option_name")
            if legacy_color or legacy_size:
                data = {
                    **data,
                    "option_axes": [
                        {"source": "color", "label": legacy_color or "Couleur"},
                        {"source": "size", "label": legacy_size or "Taille"},
                    ],
                }
        return data

    @model_validator(mode="after")
    def _unique_axis_sources(self) -> "ImportProfileConfig":
        sources = [axis.source for axis in self.option_axes]
        if len(sources) != len(set(sources)):
            raise ValueError(
                "chaque champ source d'option ne peut être utilisé qu'une fois"
            )
        return self


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
