"""Request/response schemas for enrichment jobs and items."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class JobSelection(BaseModel):
    """Product selection: explicit Tillin ids or a tag (exactly one)."""

    ids: list[int] | None = None
    tag: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "JobSelection":
        if (self.ids is None or len(self.ids) == 0) == (self.tag is None):
            raise ValueError("Provide exactly one of 'ids' or 'tag'")
        return self


class JobCreateRequest(BaseModel):
    selection: JobSelection
    config: dict[str, Any] = Field(default_factory=dict)


class JobCounts(BaseModel):
    total: int = 0
    pending: int = 0
    processing: int = 0
    ready_for_review: int = 0
    approved: int = 0
    applied: int = 0
    rejected: int = 0
    failed: int = 0


class JobPublic(BaseModel):
    id: int
    status: str
    selection_json: dict[str, Any]
    config_json: dict[str, Any]
    counts: JobCounts
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Wall-clock processing time in seconds, once the run has settled.
    duration_seconds: float | None = None


class RetryResult(BaseModel):
    """Issue d'une relance « même fiche » (`source_url` / `keep_source`).

    `pending` tant que la fiche n'est pas retraitée. Ensuite :
    `source_used` (la page demandée a servi), `source_url_effective` (page
    réellement utilisée, None = aucune), `fallback` (repli sur la recherche
    automatique ou les données catalogue : page morte, site bloqué, aucune
    donnée — à vérifier avant de valider), fiches « pour une couleur »
    rattachées (`extra_sources_kept`) ou perdues (`extra_sources_lost`).
    """

    source_requested: str
    pending: bool = False
    source_used: bool | None = None
    source_url_effective: str | None = None
    fallback: bool | None = None
    failure: str | None = None
    extra_sources_kept: list[str] = Field(default_factory=list)
    extra_sources_lost: list[str] = Field(default_factory=list)


def retry_result_of(resolution: dict[str, Any] | None) -> RetryResult | None:
    resolution = resolution or {}
    pending = resolution.get("source_url_override")
    if pending:
        extras = resolution.get("retry_extras") or {}
        return RetryResult(
            source_requested=str(pending),
            pending=True,
            extra_sources_kept=[
                str(s.get("url")) for s in extras.get("sources") or [] if s.get("url")
            ],
        )
    raw = resolution.get("retry")
    if isinstance(raw, dict) and raw.get("source_requested"):
        return RetryResult.model_validate(raw)
    return None


class ItemPublic(BaseModel):
    id: int
    job_id: int
    tillin_product_id: int
    # Catalog title snapshot (last processing run) — task lists/breadcrumbs
    # label by title; None for items processed before the snapshot existed.
    product_title: str | None = None
    status: str
    source_url: str | None = None
    source_method: str | None = None
    match_score: float | None = None
    resolution_json: dict[str, Any] | None = None
    staged_title: str | None = None
    staged_description: str | None = None
    staged_description_html: str | None = None
    staged_meta: str | None = None
    staged_price: str | None = None
    staged_images_json: list[Any] | None = None
    staged_weights_json: list[Any] | None = None
    apply_fields_json: dict[str, Any] | None = None
    error: str | None = None
    attempt_count: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Wall-clock processing time in seconds, once the item has settled.
    duration_seconds: float | None = None
    updated_at: datetime
    # Issue de la dernière relance « même fiche » (None sinon).
    retry_result: RetryResult | None = None

    @model_validator(mode="after")
    def _compute_duration(self) -> "ItemPublic":
        if self.started_at is not None and self.finished_at is not None:
            self.duration_seconds = (self.finished_at - self.started_at).total_seconds()
        self.retry_result = retry_result_of(self.resolution_json)
        return self


class JobItemsRetryRequest(BaseModel):
    """Relance groupée : les fiches choisies dans la liste du job."""

    item_ids: list[int] = Field(min_length=1, max_length=500)
    # Reprendre la page source actuelle de chaque fiche (sans nouvelle
    # recherche) ; une fiche sans page source est recherchée comme avant.
    keep_source: bool = False


class ItemRetryRequest(BaseModel):
    """Relance d'une fiche. `source_url` : page produit à reprendre telle
    quelle (pas de recherche) ; `keep_source` : reprendre la page source
    actuelle. Sans l'un ni l'autre : relance complète, recherche comprise."""

    source_url: str | None = Field(default=None, max_length=2048)
    keep_source: bool = False


class ItemApplyRequest(BaseModel):
    """Optional apply body — required semantics for RE-propagation.

    `apply_fields` (même forme que `apply_fields_json` : {"title": bool, …,
    "image_urls": [...], "weight_variant_ids": [...]}) remplace la sélection
    stockée pour CETTE écriture. Sur un item déjà `applied`, il est
    OBLIGATOIRE : re-propager sans sélection explicite re-pousserait toutes
    les images (endpoint Xano append-only → doublons).
    """

    apply_fields: dict[str, Any] | None = None


class ItemPatchRequest(BaseModel):
    """Editable staged fields (review-time corrections)."""

    staged_title: str | None = None
    staged_description: str | None = None
    staged_description_html: str | None = None
    staged_meta: str | None = None
    staged_price: str | None = None
    staged_images_json: list[Any] | None = None
    staged_weights_json: list[Any] | None = None
    # Per-field keep/drop for the apply step ({"title": false, ...}), plus
    # fine-grained selections: `image_urls` (subset of staged image URLs) and
    # `weight_variant_ids` (subset of staged weight variants).
    apply_fields_json: dict[str, Any] | None = None


class ItemImageNormalizeRequest(BaseModel):
    """Per-image review action: normalize one staged image (or revert it)."""

    url: str = Field(min_length=1)
    revert: bool = False


class ProductEnrichmentStatus(BaseModel):
    """Dernier passage d'enrichissement d'un produit (badge de la liste)."""

    product_id: int
    item_id: int
    job_id: int
    status: str
    updated_at: datetime


class ItemHistoryEntry(BaseModel):
    """Trace compacte d'un passage d'enrichissement pour UN produit.

    Alimente le panneau produit (« déjà enrichi ? écarté ? quand ? ») sans
    embarquer les champs staged (lourds) d'ItemPublic.
    """

    id: int
    job_id: int
    status: str
    updated_at: datetime
    finished_at: datetime | None = None


class PagePreview(BaseModel):
    """Thumbnail of a resolution page (og:image) — best-effort, may be empty."""

    url: str
    image_url: str | None = None


class ItemResolveRequest(BaseModel):
    """Manually point an item at a specific source product page.

    Any http(s) URL is accepted since the web-extraction fallback: non-Shopify
    pages go through LLM extraction (the old validator required a Shopify
    `/products/` URL and would have blocked e.g. salomon.com in the review).
    """

    source_url: str = Field(min_length=1)

    @model_validator(mode="after")
    def _looks_like_url(self) -> "ItemResolveRequest":
        if not self.source_url.startswith(("http://", "https://")):
            raise ValueError("Expected a product page URL (http/https)")
        return self


class ItemExtraSourceRequest(BaseModel):
    """Associe une fiche supplémentaire (une page par couleur) à l'item.

    Seules ses images sont stagées, taguées `color` ; la copie, la meta, le
    titre, le prix et les poids restent issus de la fiche principale.
    """

    source_url: str = Field(min_length=1)
    color: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def _looks_like_url(self) -> "ItemExtraSourceRequest":
        if not self.source_url.startswith(("http://", "https://")):
            raise ValueError("Expected a product page URL (http/https)")
        self.color = self.color.strip()
        if not self.color:
            raise ValueError("Expected a non-empty color")
        return self


class ItemMainColorRequest(BaseModel):
    """Couleur du produit illustrée par la fiche principale (null = aucune)."""

    color: str | None = Field(default=None, max_length=120)
