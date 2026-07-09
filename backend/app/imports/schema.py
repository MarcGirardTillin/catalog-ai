"""Import sprint frozen contract: the normalized product schema (I1).

This is the boundary every import lot builds against (owned by the main
thread — coordinate before changing anything here):

- parsers produce a :class:`RawDocument` (`parse_file`),
- the LLM extraction produces :class:`ExtractionResult` (list of
  :class:`ImportedProduct` + usage), implementing :class:`Extractor`,
- the job processor stages one ``import_item`` row per product
  (``payload_json = ImportedProduct.model_dump(mode="json")``).

Design (plan « Import sprint », semantics confirmed 2026-07-09):
- The schema is a clean model aligned with Tillin's product data design
  (`tables_xano/`), NOT the import CSV template — but it must render
  losslessly to that CSV (I2) and map to the Xano entities (I3).
- Grain: product grouped by supplier reference; **color and size are
  variant axes** (Tillin options « Couleur » / « Taille »).
- Extraction carries raw supplier facts only. Boutique conventions
  (pricing rule, brand rule, category mapping, season) are applied later
  by profiles (I2) — never guessed here.
- EAN/price values must be byte-identical to the source document
  (cross-checked by the extractor; never generated).
"""

from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, Field

# Confidence per field name (0.0-1.0), e.g. {"title": 0.95, "ean": 1.0}.
# Missing key = the extractor offered no self-assessment for that field.
Confidence = dict[str, float]


class ImportedVariant(BaseModel):
    """One sellable variant (one size of one color), one CSV row later."""

    ean: str | None = None  # barcode as printed in the source (digits kept raw)
    color: str | None = None  # Tillin option « Couleur »
    size: str | None = None  # Tillin option « Taille »
    quantity: int | None = None  # ordered quantity
    wholesale_price: Decimal | None = None  # per-unit purchase price
    retail_price: Decimal | None = None  # supplier public/suggested price
    supplier_sku: str | None = None  # supplier's own SKU when distinct from EAN
    confidence: Confidence = Field(default_factory=dict)


class ImportedProduct(BaseModel):
    """One product (a supplier reference) with its extracted variants."""

    supplier_ref: str  # → Tillin product_reference_code
    title: str | None = None
    brand: str | None = None  # raw label; profile may override (I2)
    category: str | None = None  # raw supplier label; profile maps it (I2)
    season: str | None = None
    gender: str | None = None  # matched to Tillin departments by the importer
    composition: str | None = None
    hs_code: str | None = None  # harmonized system code
    manufacturing_country: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    variants: list[ImportedVariant] = Field(default_factory=list)
    confidence: Confidence = Field(default_factory=dict)


class RawTable(BaseModel):
    """One table of raw cell values (a sheet, or a detected PDF table)."""

    rows: list[list[str]]
    sheet: str | None = None


class RawDocument(BaseModel):
    """Parser output: the source document, structure-preserved, unparsed.

    PDFs pass through as bytes (Claude document/vision reads the pages
    directly); tabular files carry their raw cells so numeric/EAN values
    can be read and cross-checked deterministically.
    """

    kind: Literal["pdf", "tabular"]
    filename: str
    pdf_bytes: bytes | None = None  # kind == "pdf"
    tables: list[RawTable] = Field(default_factory=list)  # kind == "tabular"
    text: str | None = None  # optional pdf text layer (cross-check aid)


class ExtractionUsage(BaseModel):
    """Token usage of one LLM call (feeds the usage metering brick, M1)."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class DocumentInfo(BaseModel):
    """Document-level facts, read once per file (purchase orders mostly).

    Never guessed: only filled when printed in the document itself.
    """

    po_number: str | None = None  # purchase-order number ("PO", "commande n°")
    supplier: str | None = None  # issuing supplier or brand name


class ExtractionResult(BaseModel):
    products: list[ImportedProduct]
    document: DocumentInfo = Field(default_factory=DocumentInfo)
    warnings: list[str] = Field(default_factory=list)  # surfaced in review
    usage: list[ExtractionUsage] = Field(default_factory=list)


class Extractor(Protocol):
    """What the import job processor runs (implemented in app.imports)."""

    def __call__(self, document: RawDocument) -> ExtractionResult: ...
