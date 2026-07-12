"""LLM extraction: :class:`RawDocument` -> :class:`ExtractionResult`.

Uses the anthropic SDK with structured outputs (``output_config.format``)
so the response is guaranteed-parseable JSON, same pattern as
``app.clients.claude``. After the call, extracted values are
cross-checked against the source to kill hallucinations:

- tabular sources (strict): every EAN and price must exist in the source
  cells — a value not found is nulled out, warned about, and gets
  confidence 0; a verified value gets confidence 1.0;
- PDF sources (best effort): no reliable text layer, so each EAN is
  validated by its EAN-13 check digit; prices keep the model's own
  confidence.
"""

import base64
import json
from decimal import Decimal, InvalidOperation
from typing import Any

import anthropic
import httpx
from pydantic import BaseModel, Field, ValidationError

from app.clients.base import ExternalServiceError, NotConfiguredError
from app.clients.claude import MAX_RETRIES as CLAUDE_MAX_RETRIES
from app.core.config import settings
from app.imports.schema import (
    Confidence,
    DocumentInfo,
    ExtractionResult,
    ExtractionUsage,
    Extractor,
    ImportedProduct,
    ImportedVariant,
    RawDocument,
)

# Large purchase orders produce a lot of JSON (hundreds of variants) —
# ~100 output tokens per variant, so 16K truncated a 186-variant order.
# Sonnet 5 allows up to 128K output; 32K covers ~300 variants comfortably.
MAX_TOKENS = 32_000

# Explicit per-request timeout: the SDK refuses non-streaming requests with a
# large max_tokens unless a timeout is set (idle-connection guard). A 250-line
# supplier file generates for a few minutes at most.
REQUEST_TIMEOUT_SECONDS = 600.0

# Tabular sources are truncated to this many serialized rows to stay
# within input limits.
MAX_TABLE_ROWS = 2000

SYSTEM_PROMPT = (
    "Tu extrais fidèlement les produits d'un bon de commande fournisseur "
    "(mode/textile).\n"
    "- Grain : un produit = une référence fournisseur ; ses variantes sont "
    "les couples couleur × taille.\n"
    "- N'invente JAMAIS une valeur. Si un champ est absent du document, "
    'renvoie une chaîne vide "".\n'
    "- Recopie les EAN chiffre à chiffre, exactement comme imprimés.\n"
    "- Les prix sont les valeurs numériques telles qu'imprimées (sans "
    "symbole monétaire), recopiées à l'identique (ex. « 39,90 »). "
    "wholesale_price = prix d'achat unitaire HT ; retail_price = prix "
    "public conseillé.\n"
    "- quantity = quantité commandée pour la variante (chiffres uniquement, "
    "chaîne vide si inconnue).\n"
    "- brand et category uniquement si elles figurent littéralement dans "
    "le document — ne les déduis jamais.\n"
    "- Pour chaque champ, fournis une auto-évaluation de confiance entre "
    "0 et 1 (mets 0 pour un champ vide).\n"
    "- Au niveau du document : po_number = numéro du bon de commande "
    "(« PO », « commande n° », « order no. »…) et supplier = nom du "
    "fournisseur ou de la marque qui émet le document, uniquement s'ils y "
    'figurent littéralement (chaîne vide "" sinon).'
)

_USER_PROMPT = (
    "Extrais tous les produits de ce bon de commande fournisseur, avec "
    "leurs variantes (couleur × taille), au format demandé."
)

# Appended when several files are extracted together: they describe the SAME
# purchase order and must be reconciled, not concatenated.
_MULTI_FILE_NOTE = (
    "\n\nCes fichiers appartiennent au MÊME bon de commande fournisseur. "
    "Réconcilie et fusionne leurs informations par référence fournisseur : "
    "une même variante peut avoir sa référence dans un fichier et son EAN ou "
    "son prix dans un autre. Ne duplique JAMAIS un produit — un produit = une "
    "référence fournisseur, agrégée sur l'ensemble des fichiers."
)


def _normalize_label(value: str) -> str:
    """Casefold + collapse whitespace, for matching a category to the tree."""
    return " ".join(value.split()).strip().casefold()


def _category_prompt(known_categories: list[str]) -> str:
    """Extra instruction: map `category` onto the boutique's own tree.

    The arborescence is user-defined (Tillin « get_all_informations »), so the
    supplier's own wording must be rapproché to an EXISTING category rather than
    copied verbatim. Paths give Claude the hierarchy for disambiguation; the
    answer is the leaf label (canonicalized deterministically after the call).
    """
    listing = "\n".join(f"- {path}" for path in known_categories)
    return (
        "\n\nCatégories existantes de la boutique (arborescence « parent > "
        "enfant ») :\n" + listing + "\n\nPour le champ category de chaque "
        "produit : choisis la catégorie EXISTANTE la plus précise (la feuille) "
        "qui correspond au produit, et renvoie exactement son dernier segment "
        "(après le dernier « > »). Si aucune catégorie existante ne correspond "
        'avec certitude, renvoie une chaîne vide "". N\'invente jamais une '
        "catégorie absente de cette liste."
    )


# NOTE: the structured-output schema deliberately has ZERO union/nullable
# parameters — the live API caps them at 16 per schema ("exponential
# compilation cost"), and a fully-nullable product schema blows past it.
# Absent values are the empty string "" (mapped to None after the call);
# a mocked transport can't catch this, so keep the schema union-free.
def _confidence_schema(fields: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {name: {"type": "number"} for name in fields},
        "required": fields,
        "additionalProperties": False,
    }


_VARIANT_FIELDS = [
    "ean",
    "color",
    "size",
    "quantity",
    "wholesale_price",
    "retail_price",
    "supplier_sku",
]
_PRODUCT_FIELDS = [
    "supplier_ref",
    "title",
    "brand",
    "category",
    "season",
    "gender",
    "composition",
    "hs_code",
    "manufacturing_country",
]

# Every field is a required string; "" means absent (see note above).
# Prices stay strings so "39,90" survives exactly as printed.
_VARIANT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        **{name: {"type": "string"} for name in _VARIANT_FIELDS},
        "confidence": _confidence_schema(_VARIANT_FIELDS),
    },
    "required": [*_VARIANT_FIELDS, "confidence"],
    "additionalProperties": False,
}

_PRODUCT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        **{name: {"type": "string"} for name in _PRODUCT_FIELDS},
        "image_urls": {"type": "array", "items": {"type": "string"}},
        "variants": {"type": "array", "items": _VARIANT_SCHEMA},
        "confidence": _confidence_schema(_PRODUCT_FIELDS),
    },
    "required": [*_PRODUCT_FIELDS, "image_urls", "variants", "confidence"],
    "additionalProperties": False,
}

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "products": {"type": "array", "items": _PRODUCT_SCHEMA},
        # Document-level facts (purchase orders): "" = absent, like the rest.
        "po_number": {"type": "string"},
        "supplier": {"type": "string"},
    },
    "required": ["products", "po_number", "supplier"],
    "additionalProperties": False,
}


# ---- raw payload models (what the model returns) ----


# Mirrors the union-free wire format: strings everywhere, "" = absent.
class _RawVariant(BaseModel):
    ean: str = ""
    color: str = ""
    size: str = ""
    quantity: str = ""
    wholesale_price: str = ""
    retail_price: str = ""
    supplier_sku: str = ""
    confidence: dict[str, float] = Field(default_factory=dict)


class _RawProduct(BaseModel):
    supplier_ref: str
    title: str = ""
    brand: str = ""
    category: str = ""
    season: str = ""
    gender: str = ""
    composition: str = ""
    hs_code: str = ""
    manufacturing_country: str = ""
    image_urls: list[str] = Field(default_factory=list)
    variants: list[_RawVariant] = Field(default_factory=list)
    confidence: dict[str, float] = Field(default_factory=dict)


class _RawExtraction(BaseModel):
    products: list[_RawProduct]
    po_number: str = ""
    supplier: str = ""


# ---- normalization helpers (cross-check) ----

_EAN_STRIP = str.maketrans("", "", "  .'’`")


def _normalize_ean(value: str) -> str:
    """Strip spaces, dots and apostrophes — digits must match exactly."""
    return value.translate(_EAN_STRIP)


def _parse_decimal(value: str) -> Decimal | None:
    """Parse a printed price into a Decimal.

    Handles both decimal-separator conventions and thousands separators:
    "39,90", "1 250.00 €", "1,143.00", "1.250,00". When both "," and "."
    appear, the LAST one is the decimal separator; a single separator
    followed by exactly 3 digits is treated as a thousands separator
    ("1,143" -> 1143) while 1-2 trailing digits mean decimals ("39,9").
    """
    cleaned = value.strip().replace(" ", "").replace(" ", "").replace("€", "")
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        decimal_sep = "," if cleaned.rindex(",") > cleaned.rindex(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        cleaned = cleaned.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif "," in cleaned or "." in cleaned:
        sep = "," if "," in cleaned else "."
        head, _, tail = cleaned.rpartition(sep)
        if cleaned.count(sep) == 1 and len(tail) != 3:
            cleaned = f"{head}.{tail}"  # decimal separator ("39,90", "24.5")
        else:
            cleaned = cleaned.replace(sep, "")  # thousands ("1,143", "1.234.567")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def ean13_is_valid(ean: str) -> bool:
    """EAN-13 check digit validation."""
    if len(ean) != 13 or not ean.isdigit():
        return False
    digits = [int(char) for char in ean]
    total = sum(d * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits[:12]))
    return (10 - total % 10) % 10 == digits[12]


def _opt(value: str) -> str | None:
    """Map the wire format's empty-string-as-absent back to None."""
    return value.strip() or None


def _kept_confidence(raw: dict[str, float], present: set[str]) -> Confidence:
    """Keep confidences only for fields that carry a value, clamped to 0-1."""
    return {
        key: min(max(value, 0.0), 1.0) for key, value in raw.items() if key in present
    }


class ClaudeExtractor:
    """Extractor backed by the Anthropic messages API (structured output)."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str | None = None,
        http_client: httpx.Client | None = None,
        known_categories: list[str] | None = None,
    ) -> None:
        if not api_key:
            raise NotConfiguredError("claude")
        self._model = model or settings.AI_DEFAULT_MODEL
        # max_retries : rejoue 429/5xx avec backoff (même règle que ClaudeClient).
        self._client = anthropic.Anthropic(
            api_key=api_key, http_client=http_client, max_retries=CLAUDE_MAX_RETRIES
        )
        # Boutique category tree (« parent > enfant » paths); when provided,
        # extracted categories are mapped onto it (prompt + canonicalization).
        self._known_categories = [c for c in (known_categories or []) if c.strip()]
        self._category_canon = {
            _normalize_label(path.rsplit(">", 1)[-1]): path.rsplit(">", 1)[-1].strip()
            for path in self._known_categories
        }

    def __call__(self, document: RawDocument | list[RawDocument]) -> ExtractionResult:
        documents = [document] if isinstance(document, RawDocument) else list(document)
        if not documents:
            raise ValueError("extractor called with no document")
        warnings: list[str] = []
        # A single document (or a one-element list) keeps the historical,
        # byte-identical single-file request; several documents are combined
        # into ONE call so Claude reconciles them.
        if len(documents) == 1:
            content = self._build_content(documents[0], warnings)
        else:
            content = self._build_multi_content(documents, warnings)

        try:
            # Thinking is disabled: extraction is mechanical transcription —
            # adaptive thinking (Sonnet 5's default) would eat into the output
            # budget without improving fidelity.
            response = self._client.with_options(
                timeout=REQUEST_TIMEOUT_SECONDS
            ).messages.create(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                thinking={"type": "disabled"},
                output_config={
                    "format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA}
                },
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.APIConnectionError as exc:
            raise ExternalServiceError("claude", "Claude is unreachable") from exc
        except anthropic.APIStatusError as exc:
            raise ExternalServiceError(
                "claude",
                "Claude returned an error response",
                detail={"upstream_status": exc.status_code},
            ) from exc

        if response.stop_reason == "refusal":
            raise ExternalServiceError("claude", "Claude refused the request")
        if response.stop_reason == "max_tokens":
            warnings.append(
                "La réponse du modèle a atteint la limite de tokens — "
                "l'extraction est possiblement tronquée."
            )

        text = "".join(block.text for block in response.content if block.type == "text")
        try:
            raw = _RawExtraction.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ExternalServiceError(
                "claude", "Claude returned an unparseable extraction payload"
            ) from exc

        products = [
            self._to_product(raw_product, warnings) for raw_product in raw.products
        ]
        self._canonicalize_categories(products)
        if len(documents) == 1:
            single = documents[0]
            if single.kind == "tabular":
                self._cross_check_tabular(products, single, warnings)
            else:
                self._cross_check_pdf(products, warnings)
        else:
            self._cross_check_multi(products, documents, warnings)

        usage = [
            ExtractionUsage(
                model=response.model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
        ]
        return ExtractionResult(
            products=products,
            document=DocumentInfo(
                po_number=_opt(raw.po_number), supplier=_opt(raw.supplier)
            ),
            warnings=warnings,
            usage=usage,
        )

    # ---- request building ----

    def _user_prompt(self) -> str:
        if self._known_categories:
            return _USER_PROMPT + _category_prompt(self._known_categories)
        return _USER_PROMPT

    def _build_content(self, document: RawDocument, warnings: list[str]) -> list[Any]:
        user_prompt = self._user_prompt()
        if document.kind == "pdf":
            if document.pdf_bytes is None:
                raise ValueError("pdf document has no pdf_bytes")
            return [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.standard_b64encode(document.pdf_bytes).decode(
                            "ascii"
                        ),
                    },
                },
                {"type": "text", "text": user_prompt},
            ]
        return [
            {
                "type": "text",
                "text": (
                    f"{user_prompt}\n\nFichier : {document.filename}\n\n"
                    + self._serialize_tables(document, warnings)
                ),
            }
        ]

    def _build_multi_content(
        self, documents: list[RawDocument], warnings: list[str]
    ) -> list[Any]:
        """One combined request for several files of the same purchase order.

        Each PDF becomes its own ``document`` block (preceded by a labeling text
        block); each tabular file becomes a text block tagged with its name.
        Claude sees everything at once and reconciles by supplier reference.
        """
        content: list[Any] = [
            {"type": "text", "text": self._user_prompt() + _MULTI_FILE_NOTE}
        ]
        for document in documents:
            if document.kind == "pdf":
                if document.pdf_bytes is None:
                    raise ValueError("pdf document has no pdf_bytes")
                content.append(
                    {"type": "text", "text": f"Fichier : {document.filename}"}
                )
                content.append(
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": base64.standard_b64encode(
                                document.pdf_bytes
                            ).decode("ascii"),
                        },
                    }
                )
            else:
                content.append(
                    {
                        "type": "text",
                        "text": (
                            f"Fichier : {document.filename}\n\n"
                            + self._serialize_tables(
                                document, warnings, label=document.filename
                            )
                        ),
                    }
                )
        return content

    def _serialize_tables(
        self, document: RawDocument, warnings: list[str], *, label: str | None = None
    ) -> str:
        lines: list[str] = []
        remaining = MAX_TABLE_ROWS
        truncated = False
        for table in document.tables:
            lines.append(f"=== Feuille : {table.sheet or document.filename} ===")
            for row in table.rows:
                if remaining == 0:
                    truncated = True
                    break
                lines.append("\t".join(row))
                remaining -= 1
            if truncated:
                break
        if truncated:
            # In a multi-file lot, name the truncated file so the warning is
            # actionable; single-file keeps the historical (unprefixed) text.
            prefix = f"{label} : " if label else ""
            warnings.append(
                f"{prefix}Source tabulaire tronquée à {MAX_TABLE_ROWS} lignes "
                "pour l'extraction — des produits peuvent manquer."
            )
        return "\n".join(lines)

    # ---- mapping ----

    def _to_product(self, raw: _RawProduct, warnings: list[str]) -> ImportedProduct:
        variants = [
            self._to_variant(raw.supplier_ref, raw_variant, warnings)
            for raw_variant in raw.variants
        ]
        fields = {
            "supplier_ref": raw.supplier_ref,
            "title": _opt(raw.title),
            "brand": _opt(raw.brand),
            "category": _opt(raw.category),
            "season": _opt(raw.season),
            "gender": _opt(raw.gender),
            "composition": _opt(raw.composition),
            "hs_code": _opt(raw.hs_code),
            "manufacturing_country": _opt(raw.manufacturing_country),
        }
        present = {key for key, value in fields.items() if value is not None}
        return ImportedProduct(
            **fields,  # type: ignore[arg-type]
            image_urls=raw.image_urls,
            variants=variants,
            confidence=_kept_confidence(raw.confidence, present),
        )

    def _to_variant(
        self, supplier_ref: str, raw: _RawVariant, warnings: list[str]
    ) -> ImportedVariant:
        quantity: int | None = None
        quantity_text = _opt(raw.quantity)
        if quantity_text is not None:
            try:
                quantity = int(quantity_text)
            except ValueError:
                warnings.append(
                    f"Quantité illisible {quantity_text!r} "
                    f"(réf {supplier_ref}) — retirée"
                )
        prices: dict[str, Decimal | None] = {}
        unreadable: list[str] = []
        for field in ("wholesale_price", "retail_price"):
            printed = _opt(getattr(raw, field))
            if printed is None:
                prices[field] = None
                continue
            value = _parse_decimal(printed)
            if value is None:
                warnings.append(
                    f"Prix illisible {printed!r} ({field}, réf {supplier_ref}) — retiré"
                )
                unreadable.append(field)
            prices[field] = value
        fields = {
            "ean": _opt(raw.ean),
            "color": _opt(raw.color),
            "size": _opt(raw.size),
            "supplier_sku": _opt(raw.supplier_sku),
        }
        present = {key for key, value in fields.items() if value is not None}
        present.update(f for f, v in prices.items() if v is not None)
        if quantity is not None:
            present.add("quantity")
        confidence = _kept_confidence(raw.confidence, present)
        for field in unreadable:
            confidence[field] = 0.0
        return ImportedVariant(
            **fields,
            quantity=quantity,
            wholesale_price=prices["wholesale_price"],
            retail_price=prices["retail_price"],
            confidence=confidence,
        )

    def _canonicalize_categories(self, products: list[ImportedProduct]) -> None:
        """Map each product's category onto the boutique tree (leaf label).

        When the tree is known, an extracted category that normalizes to an
        existing leaf is rewritten to that leaf's canonical casing (confidence
        1.0). An unmatched value is kept verbatim so the reviewer can still map
        it by hand — never dropped.
        """
        if not self._category_canon:
            return
        for product in products:
            if product.category is None:
                continue
            # Claude may echo a full « parent > leaf » path; keep the leaf.
            leaf = product.category.rsplit(">", 1)[-1]
            canonical = self._category_canon.get(_normalize_label(leaf))
            if canonical is not None:
                product.category = canonical
                product.confidence["category"] = 1.0

    # ---- cross-checks ----

    def _cross_check_tabular(
        self,
        products: list[ImportedProduct],
        document: RawDocument,
        warnings: list[str],
    ) -> None:
        ean_cells: set[str] = set()
        price_cells: set[Decimal] = set()
        for table in document.tables:
            for row in table.rows:
                for cell in row:
                    stripped = cell.strip()
                    if not stripped:
                        continue
                    ean_cells.add(_normalize_ean(stripped))
                    number = _parse_decimal(stripped)
                    if number is not None:
                        price_cells.add(number)

        for product in products:
            for variant in product.variants:
                if variant.ean is not None:
                    if _normalize_ean(variant.ean.strip()) not in ean_cells:
                        warnings.append(
                            f"EAN {variant.ean} introuvable dans la source — retiré"
                        )
                        variant.ean = None
                        variant.confidence["ean"] = 0.0
                    else:
                        variant.confidence["ean"] = 1.0
                for field in ("wholesale_price", "retail_price"):
                    value: Decimal | None = getattr(variant, field)
                    if value is None:
                        continue
                    # Decimal equality ignores trailing zeros (39.90 == 39.9).
                    if value not in price_cells:
                        warnings.append(
                            f"Prix {value} ({field}, réf "
                            f"{product.supplier_ref}) introuvable dans la "
                            "source — retiré"
                        )
                        setattr(variant, field, None)
                        variant.confidence[field] = 0.0
                    else:
                        variant.confidence[field] = 1.0

    def _cross_check_pdf(
        self, products: list[ImportedProduct], warnings: list[str]
    ) -> None:
        for product in products:
            for variant in product.variants:
                if variant.ean is None:
                    continue
                normalized = _normalize_ean(variant.ean.strip())
                if not ean13_is_valid(normalized):
                    warnings.append(
                        f"EAN {variant.ean} invalide (clé de contrôle EAN-13) — retiré"
                    )
                    variant.ean = None
                    variant.confidence["ean"] = 0.0

    def _cross_check_multi(
        self,
        products: list[ImportedProduct],
        documents: list[RawDocument],
        warnings: list[str],
    ) -> None:
        """Cross-check against the UNION of every file in the lot.

        EANs/prices are verified against the pooled cells of all tabular files.
        An EAN absent from that pool is validated by its EAN-13 check digit when
        the lot contains at least one PDF (best-effort, as for a lone PDF),
        otherwise dropped. Prices absent from the tabular pool are dropped unless
        the lot is 100% PDF, in which case the model's confidence is kept.
        """
        has_pdf = any(document.kind == "pdf" for document in documents)
        tabular_docs = [d for d in documents if d.kind == "tabular"]
        all_pdf = not tabular_docs
        ean_cells: set[str] = set()
        price_cells: set[Decimal] = set()
        for document in tabular_docs:
            for table in document.tables:
                for row in table.rows:
                    for cell in row:
                        stripped = cell.strip()
                        if not stripped:
                            continue
                        ean_cells.add(_normalize_ean(stripped))
                        number = _parse_decimal(stripped)
                        if number is not None:
                            price_cells.add(number)

        for product in products:
            for variant in product.variants:
                if variant.ean is not None:
                    normalized = _normalize_ean(variant.ean.strip())
                    if normalized in ean_cells:
                        variant.confidence["ean"] = 1.0
                    elif has_pdf and ean13_is_valid(normalized):
                        pass  # unverifiable in text but plausible; keep as-is
                    else:
                        reason = (
                            "invalide (clé de contrôle EAN-13)"
                            if has_pdf
                            else "introuvable dans la source"
                        )
                        warnings.append(f"EAN {variant.ean} {reason} — retiré")
                        variant.ean = None
                        variant.confidence["ean"] = 0.0
                if all_pdf:
                    # No tabular pool to verify prices against: keep the model's
                    # own confidence, exactly like a lone PDF source.
                    continue
                for field in ("wholesale_price", "retail_price"):
                    value: Decimal | None = getattr(variant, field)
                    if value is None:
                        continue
                    if value not in price_cells:
                        warnings.append(
                            f"Prix {value} ({field}, réf "
                            f"{product.supplier_ref}) introuvable dans la "
                            "source — retiré"
                        )
                        setattr(variant, field, None)
                        variant.confidence[field] = 0.0
                    else:
                        variant.confidence[field] = 1.0


def build_extractor(
    api_key: str,
    *,
    model: str | None = None,
    http_client: httpx.Client | None = None,
    known_categories: list[str] | None = None,
) -> Extractor:
    """Build the Claude-backed :class:`Extractor` (frozen entry point)."""
    return ClaudeExtractor(
        api_key,
        model=model,
        http_client=http_client,
        known_categories=known_categories,
    )
