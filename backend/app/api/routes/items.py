"""Enrichment item routes: detail, staged edits, review decisions, apply."""

from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import func, select

from app.api.deps import (
    CurrentUserDep,
    JobRunnerDep,
    PhotoroomDep,
    PipelineDep,
    SessionDep,
    XanoDep,
    require_feature,
)
from app.api.exceptions import AppException
from app.api.schemas import PaginatedResponse, Product
from app.api.schemas.enrichment import (
    ItemApplyRequest,
    ItemExtraSourceRequest,
    ItemHistoryEntry,
    ItemImageNormalizeRequest,
    ItemMainColorRequest,
    ItemPatchRequest,
    ItemPublic,
    ItemResolveRequest,
    PagePreview,
    ProductEnrichmentStatus,
)
from app.api.services.accounts import resolve_account_id
from app.api.services.credits import credit_grid, require_credits
from app.api.services.enrichment import (
    add_item_extra_source,
    apply_item,
    generate_item_copy,
    get_item,
    latest_items_by_product,
    normalize_item_image,
    remove_item_extra_source,
    resolve_item_from_url,
    retry_item,
    review_item,
    set_item_main_color,
    update_staged_fields,
)
from app.clients.xano import XanoError
from app.destinations.xano_tillin import XanoTillinDestination
from app.enrich.extra_sources import extra_source_urls
from app.models import EnrichmentItem
from app.sources.preview import fetch_page_preview

# Review = module « Enrichissement » (la normalisation d'images du review
# en fait partie : c'est le flux d'enrichissement, pas le studio).
router = APIRouter(
    prefix="/items",
    tags=["items"],
    dependencies=[Depends(require_feature("feature_enrich"))],
)


@router.get("", response_model=list[ItemHistoryEntry])
def list_product_item_history(
    product_id: int, db: SessionDep, current_user: CurrentUserDep
) -> list[ItemHistoryEntry]:
    """Historique d'enrichissement d'UN produit (plus récent en premier).

    Alimente le panneau produit : « déjà enrichi le … / écarté le … ».
    Scopé compte (comme toute lecture d'items) ; limité aux 20 derniers.
    """
    account_id = resolve_account_id(db, current_user)
    rows = db.scalars(
        select(EnrichmentItem)
        .where(
            EnrichmentItem.account_id == account_id,
            EnrichmentItem.tillin_product_id == product_id,
        )
        .order_by(EnrichmentItem.id.desc())
        .limit(20)
    ).all()
    return [ItemHistoryEntry.model_validate(row, from_attributes=True) for row in rows]


# Statuts proposés au filtre « Enrichis » de la liste produits.
EnrichedFilter = Literal[
    "any", "ready_for_review", "approved", "applied", "rejected", "failed"
]
_ENRICHED_PAGE_WORKERS = 8


@router.get("/product-status", response_model=list[ProductEnrichmentStatus])
def list_product_enrichment_status(
    db: SessionDep,
    current_user: CurrentUserDep,
    product_ids: Annotated[list[int], Query(max_length=200)],
) -> list[ProductEnrichmentStatus]:
    """Badge « enrichi » de la liste produits : dernier passage de chacun
    des produits affichés (absents = jamais enrichis). Scopé compte."""
    account_id = resolve_account_id(db, current_user)
    rows = db.scalars(
        latest_items_by_product(account_id).where(
            EnrichmentItem.tillin_product_id.in_(product_ids)
        )
    ).all()
    return [
        ProductEnrichmentStatus(
            product_id=row.tillin_product_id,
            item_id=row.id,
            job_id=row.job_id,
            status=row.status,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.get("/enriched-products", response_model=PaginatedResponse[Product])
def list_enriched_products(
    db: SessionDep,
    current_user: CurrentUserDep,
    xano: XanoDep,
    enrichment: EnrichedFilter = "any",
    search: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[Product]:
    """Filtre « Enrichis » de la liste produits (Marc 2026-10-19).

    La recherche Tillin ne filtre pas par liste d'ids : la page vient des
    items locaux (dernier passage par produit, plus récent d'abord, statut
    et titre filtrables), puis chaque produit est relu dans Tillin. Les
    autres filtres catalogue ne s'appliquent pas à cette vue.
    """
    account_id = resolve_account_id(db, current_user)
    query = latest_items_by_product(account_id)
    if enrichment != "any":
        query = query.where(EnrichmentItem.status == enrichment)
    text = (search or "").strip()
    if text:
        query = query.where(EnrichmentItem.product_title.ilike(f"%{text}%"))
    total = int(
        db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
        or 0
    )
    rows = db.scalars(query.offset((page - 1) * per_page).limit(per_page)).all()
    wanted = [(row.tillin_product_id, row.product_title) for row in rows]

    def read(entry: tuple[int, str | None]) -> Product:
        product_id, title = entry
        try:
            product = xano.get_product(product_id)
        except XanoError:
            product = None
        # Produit supprimé ou illisible : ligne minimale (pagination juste).
        return product or Product(id=product_id, title=title)

    with ThreadPoolExecutor(max_workers=_ENRICHED_PAGE_WORKERS) as pool:
        products = list(pool.map(read, wanted))
    return PaginatedResponse(
        items=products,
        total=total,
        page=page,
        page_size=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


@router.get("/{item_id}", response_model=ItemPublic)
def read_item(item_id: int, db: SessionDep, current_user: CurrentUserDep) -> ItemPublic:
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    return ItemPublic.model_validate(item, from_attributes=True)


@router.get("/{item_id}/product", response_model=Product)
def read_item_product(
    item_id: int, db: SessionDep, current_user: CurrentUserDep, xano: XanoDep
) -> Product:
    """Fetch the item's current Tillin product (before/after review context)."""
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    product = xano.get_product(item.tillin_product_id)
    if product is None:
        raise AppException(
            status_code=404,
            code="not_found",
            message=f"Product {item.tillin_product_id} not found in Tillin",
        )
    return product


@router.post("/{item_id}/resolve", response_model=ItemPublic)
def resolve_item_route(
    item_id: int,
    payload: ItemResolveRequest,
    db: SessionDep,
    current_user: CurrentUserDep,
    pipeline: PipelineDep,
) -> ItemPublic:
    """Manually resolve an item from a chosen source page and re-stage it."""
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    item = resolve_item_from_url(
        db, item, payload.source_url, stage=pipeline.stage_from_url
    )
    return ItemPublic.model_validate(item, from_attributes=True)


@router.post("/{item_id}/sources", response_model=ItemPublic)
def add_item_source_route(
    item_id: int,
    payload: ItemExtraSourceRequest,
    db: SessionDep,
    current_user: CurrentUserDep,
    pipeline: PipelineDep,
) -> ItemPublic:
    """Associe une fiche supplémentaire à une couleur du produit.

    Les images de la fiche s'ajoutent en fin de galerie, taguées couleur ;
    la copie, la meta, le titre, le prix et les poids restent ceux de la
    fiche principale. Même URL déjà associée → ses images sont remplacées.
    Métering identique à la résolution manuelle (aucun débit de crédit).
    """
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    item = add_item_extra_source(
        db, item, payload.source_url, payload.color, stage=pipeline.stage_extra_source
    )
    return ItemPublic.model_validate(item, from_attributes=True)


@router.delete("/{item_id}/sources", response_model=ItemPublic)
def remove_item_source_route(
    item_id: int,
    source_url: str,
    db: SessionDep,
    current_user: CurrentUserDep,
) -> ItemPublic:
    """Retire une fiche supplémentaire (query `source_url`) et ses images."""
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    item = remove_item_extra_source(db, item, source_url)
    return ItemPublic.model_validate(item, from_attributes=True)


@router.put("/{item_id}/main-color", response_model=ItemPublic)
def set_item_main_color_route(
    item_id: int,
    payload: ItemMainColorRequest,
    db: SessionDep,
    current_user: CurrentUserDep,
) -> ItemPublic:
    """Couleur du produit illustrée par la fiche principale (null = aucune)."""
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    item = set_item_main_color(db, item, payload.color)
    return ItemPublic.model_validate(item, from_attributes=True)


@router.get("/{item_id}/page-preview", response_model=PagePreview)
def page_preview_route(
    item_id: int,
    url: str,
    db: SessionDep,
    current_user: CurrentUserDep,
) -> PagePreview:
    """Thumbnail (og:image) of one of the item's resolution pages.

    Best-effort : image_url absente quand la page ne publie pas de visuel de
    partage ou ne répond pas. L'URL demandée doit être la page source de
    l'item, l'un de ses candidats ou une fiche supplémentaire par couleur —
    jamais une URL arbitraire (anti-SSRF).
    """
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    allowed = (
        {item.source_url}
        | {
            str(candidate.get("url"))
            for candidate in (item.resolution_json or {}).get("candidates") or []
            if isinstance(candidate, dict)
        }
        | extra_source_urls(item)
    )
    if url not in allowed:
        raise AppException(
            status_code=422,
            code="unknown_page",
            message="URL is not one of this item's resolution pages",
        )
    return PagePreview(url=url, image_url=fetch_page_preview(url))


@router.post("/{item_id}/generate-copy", response_model=ItemPublic)
def generate_item_copy_route(
    item_id: int,
    db: SessionDep,
    current_user: CurrentUserDep,
    pipeline: PipelineDep,
) -> ItemPublic:
    """Generate the copy from catalog data alone (source left unresolved).

    The batch withholds the description when no source page cleared the
    confidence gate; the reviewer can either confirm a source (resolve) or
    ignore the candidates and ask for a catalog-only generation here. Claude
    usage is metered as usual; the item's enrichment credit was already
    consumed at queue time — no extra debit."""
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    item = generate_item_copy(db, item, stage=pipeline.stage_copy_only)
    return ItemPublic.model_validate(item, from_attributes=True)


@router.post("/{item_id}/retry", response_model=ItemPublic)
def retry_item_route(
    item_id: int,
    db: SessionDep,
    current_user: CurrentUserDep,
    background: BackgroundTasks,
    run_job: JobRunnerDep,
) -> ItemPublic:
    """Requeue one item for a full re-generation and kick the worker."""
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    item = retry_item(db, item, launcher_user_id=current_user.id)
    background.add_task(run_job, item.job_id)
    return ItemPublic.model_validate(item, from_attributes=True)


@router.patch("/{item_id}", response_model=ItemPublic)
def patch_item(
    item_id: int,
    payload: ItemPatchRequest,
    db: SessionDep,
    current_user: CurrentUserDep,
) -> ItemPublic:
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    item = update_staged_fields(db, item, payload.model_dump(exclude_unset=True))
    return ItemPublic.model_validate(item, from_attributes=True)


@router.post(
    "/{item_id}/images/normalize",
    response_model=ItemPublic,
    # Normaliser une image (détourage Photoroom) = module Studio, même
    # depuis le review d'enrichissement : c'est le traitement payant qui est
    # vendu à part, pas le flux dans lequel il est déclenché (décision Marc
    # 2026-07-16 — le review restait un contournement du blocage studio).
    dependencies=[Depends(require_feature("feature_studio"))],
)
def normalize_item_image_route(
    item_id: int,
    payload: ItemImageNormalizeRequest,
    db: SessionDep,
    current_user: CurrentUserDep,
    photoroom: PhotoroomDep,
) -> ItemPublic:
    """Normalize (or revert) one staged image, chosen by the reviewer.

    The batch stages original source images; each one is normalized on demand
    here (Photoroom, metered on the item's job). The Photoroom dependency
    resolves first: missing key = clean 503, nothing written.
    """
    account_id = resolve_account_id(db, current_user)
    if not payload.revert:
        require_credits(db, account_id, credit_grid(db, account_id)["image_process"])
    item = get_item(db, account_id=account_id, item_id=item_id)
    item = normalize_item_image(
        db, item, photoroom, url=payload.url, revert=payload.revert
    )
    return ItemPublic.model_validate(item, from_attributes=True)


@router.post("/{item_id}/approve", response_model=ItemPublic)
def approve_item(
    item_id: int, db: SessionDep, current_user: CurrentUserDep
) -> ItemPublic:
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    item = review_item(db, item, "approved")
    return ItemPublic.model_validate(item, from_attributes=True)


@router.post("/{item_id}/reject", response_model=ItemPublic)
def reject_item(
    item_id: int, db: SessionDep, current_user: CurrentUserDep
) -> ItemPublic:
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    item = review_item(db, item, "rejected")
    return ItemPublic.model_validate(item, from_attributes=True)


@router.post("/{item_id}/apply", response_model=ItemPublic)
def apply_item_route(
    item_id: int,
    db: SessionDep,
    current_user: CurrentUserDep,
    xano: XanoDep,
    payload: ItemApplyRequest | None = None,
) -> ItemPublic:
    """Write an approved item's staged enrichment back to Tillin (Xano).

    Avec un corps `apply_fields`, la sélection remplace celle stockée — c'est
    aussi la clé de la RE-propagation d'un item déjà `applied` (sélection
    explicite obligatoire : l'endpoint images Xano est append-only).
    """
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    item = apply_item(
        db,
        item,
        XanoTillinDestination(xano),
        apply_fields=payload.apply_fields if payload else None,
    )
    return ItemPublic.model_validate(item, from_attributes=True)
