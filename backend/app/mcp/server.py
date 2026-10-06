"""Outils MCP CatalogAI : catalogue, enrichissements, imports.

Les outils réutilisent les fonctions de route de l'API (mêmes contrôles :
scoping, crédits, états autorisés) sous la garde commune `run_tool`
(utilisateur du jeton, module du compte). Réponses compactes et paginées ;
les actions qui écrivent dans Tillin (`apply_item`, `transfer_import`)
renvoient un APERÇU tant que `confirm` n'est pas vrai.
"""

import threading
from datetime import date, datetime, time, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from sqlalchemy import select

from app.api.deps import get_job_runner
from app.api.exceptions import AppException
from app.api.routes import imports as import_routes
from app.api.routes import items as item_routes
from app.api.routes import jobs as job_routes
from app.api.routes import locations as location_routes
from app.api.schemas.enrichment import ItemPublic, JobCreateRequest, JobSelection
from app.api.schemas.imports import ImportTransferRequest
from app.api.services.credits import balance as credit_balance
from app.api.services.credits import credit_grid
from app.api.services.imaging import account_settings
from app.mcp.auth import ApiTokenVerifier
from app.mcp.guard import ToolContext, run_tool
from app.models import Account, EnrichmentItem, EnrichmentJob

INSTRUCTIONS = (
    "CatalogAI (Tillin) : catalogue produits d'une boutique, enrichissement des "
    "fiches par IA, imports de bons de commande fournisseurs. Commencez par "
    "catalogai_get_account_overview pour connaître les modules actifs et le "
    "solde de crédits. Les traitements longs (enrichissement) renvoient un "
    "identifiant : suivez-les avec catalogai_get_job_status. Les actions qui "
    "écrivent dans Tillin demandent confirm=true après un aperçu."
)

mcp = FastMCP(name="CatalogAI", instructions=INSTRUCTIONS, auth=ApiTokenVerifier())

# Remplaçable dans les tests (pas de vrai worker).
job_runner = get_job_runner


def _spawn(background: BackgroundTasks) -> None:
    """Exécute hors requête les tâches de fond posées par une route (worker
    d'enrichissement…), comme FastAPI après la réponse."""
    tasks = list(background.tasks)
    if not tasks:
        return

    def run() -> None:
        for task in tasks:
            task.func(*task.args, **task.kwargs)

    threading.Thread(target=run, name="mcp-background", daemon=True).start()


def _clip(text: str | None, limit: int) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _read_only(title: str) -> ToolAnnotations:
    return ToolAnnotations(title=title, read_only_hint=True, open_world_hint=False)


def _write(title: str, *, destructive: bool = False) -> ToolAnnotations:
    return ToolAnnotations(
        title=title,
        read_only_hint=False,
        destructive_hint=destructive,
        idempotent_hint=False,
        open_world_hint=False,
    )


# --- Compte -----------------------------------------------------------------


@mcp.tool(
    name="catalogai_get_account_overview",
    annotations=_read_only("Compte CatalogAI"),
)
async def get_account_overview() -> dict[str, Any]:
    """Compte de l'utilisateur : modules activés (import, enrichissement,
    studio), solde de crédits, coût en crédits par action, et état de la
    connexion Tillin. À appeler en premier."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        settings = account_settings(ctx.db, ctx.account_id)
        account = ctx.db.get(Account, ctx.account_id)
        everything = ctx.user.is_admin
        return {
            "user": ctx.user.email,
            "account": account.name if account else None,
            "modules": {
                "import": everything or settings.feature_import,
                "enrichment": everything or settings.feature_enrich,
                "studio": everything or settings.feature_studio,
            },
            "credits_balance": credit_balance(ctx.db, ctx.account_id),
            "credit_costs": credit_grid(ctx.db, ctx.account_id),
            "tillin_session": "active" if ctx.user.xano_token else "missing",
        }

    return await run_tool("get_account_overview", None, work)


# --- Catalogue ----------------------------------------------------------------


def _product_summary(product: Any) -> dict[str, Any]:
    colors = sorted({v.color for v in product.variants if v.color})
    return {
        "id": product.id,
        "title": product.title,
        "reference": product.reference_code,
        "brand": product.brand.name if product.brand else None,
        "category": product.category,
        "price": str(product.price) if product.price is not None else None,
        "variants": len(product.variants),
        "colors": colors,
        "images": len(product.images),
    }


@mcp.tool(
    name="catalogai_search_products",
    annotations=_read_only("Rechercher des produits"),
)
async def search_products(
    query: Annotated[
        str | None, Field(description="Texte libre : titre, référence, code-barres")
    ] = None,
    brand: Annotated[
        str | None,
        Field(description="Filtre marque par son NOM (ex. « Le Petit Souk »)"),
    ] = None,
    brand_id: Annotated[
        int | None, Field(description="Filtre marque (id Tillin)")
    ] = None,
    page: Annotated[int, Field(ge=1)] = 1,
    per_page: Annotated[int, Field(ge=1, le=25)] = 10,
) -> dict[str, Any]:
    """Recherche dans le catalogue Tillin de la boutique (résumé par produit :
    id, titre, référence, marque, prix, couleurs, nombre d'images). La marque
    se donne par son nom (`brand`) ou son id (`brand_id`)."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        wanted = brand_id
        if wanted is None and brand:
            wanted = int(_resolve_brand(ctx, brand)["id"])
        result = ctx.xano.search_products(
            text=query, brand=wanted, page=page, per_page=per_page
        )
        return {
            "total": result.total,
            "page": page,
            "products": [_product_summary(p) for p in result.items],
        }

    return await run_tool("search_products", None, work)


@mcp.tool(name="catalogai_get_product", annotations=_read_only("Fiche produit"))
async def get_product(product_id: int) -> dict[str, Any]:
    """Fiche d'un produit Tillin : description, variantes (code-barres,
    couleur, taille, prix, stock) et images."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        product = ctx.xano.get_product(product_id)
        if product is None:
            raise AppException(
                status_code=404, code="not_found", message="Produit introuvable"
            )
        return {
            **_product_summary(product),
            "season": product.season,
            "department": product.department,
            "composition": product.composition,
            "tags": product.tags,
            "description": _clip(product.description, 1500),
            "meta_description": product.meta_description,
            "variant_list": [
                {
                    "id": v.id,
                    "sku": v.sku,
                    "barcode": v.barcode,
                    "color": v.color,
                    "size": v.size,
                    "price": str(v.price) if v.price is not None else None,
                    "stock": v.stock_quantity,
                }
                for v in product.variants[:60]
            ],
            "image_urls": [image.url for image in product.images[:12]],
        }

    return await run_tool("get_product", None, work)


PARIS = ZoneInfo("Europe/Paris")
# Produits d'une marque relus dans Tillin pour filtrer les fiches enrichies
# (pas de lecture groupée par ids côté Tillin) : 5 pages de 100 au plus.
_BRAND_PRODUCT_PAGES = 5
_TODAY_WORDS = ("today", "aujourd'hui", "aujourdhui")
_YESTERDAY_WORDS = ("yesterday", "hier")


def _day(value: str) -> date:
    text = value.strip().lower()
    today = datetime.now(PARIS).date()
    if text in _TODAY_WORDS:
        return today
    if text in _YESTERDAY_WORDS:
        return today - timedelta(days=1)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ToolError(
            f"Date illisible « {value} » : utilisez AAAA-MM-JJ, today ou yesterday."
        ) from exc


def _day_range(since: str, until: str | None) -> tuple[datetime, datetime]:
    """Du début du jour `since` à la fin du jour `until` (inclus), heure de
    Paris ; sans `until` : jusqu'à maintenant."""
    start = datetime.combine(_day(since), time.min, PARIS)
    if until is None:
        return start, datetime.now(PARIS) + timedelta(seconds=1)
    end = datetime.combine(_day(until), time.min, PARIS) + timedelta(days=1)
    return start, end


def _resolve_brand(ctx: ToolContext, name: str) -> dict[str, Any]:
    """Marque Tillin par son nom (exact, sinon unique contenant), ou une
    erreur qui liste les candidates."""
    wanted = name.strip().casefold()
    brands = [b for b in ctx.xano.list_brands() if b.id is not None and b.name]
    exact = [b for b in brands if (b.name or "").casefold() == wanted]
    matches = exact or [b for b in brands if wanted in (b.name or "").casefold()]
    if len(matches) == 1:
        return {"id": matches[0].id, "name": matches[0].name}
    if not matches:
        raise ToolError(
            f"Aucune marque « {name} » dans le catalogue : essayez "
            "catalogai_list_brands pour voir les noms exacts."
        )
    names = ", ".join(sorted(b.name or "" for b in matches)[:10])
    raise ToolError(f"Plusieurs marques correspondent à « {name} » : {names}.")


def _brand_product_ids(ctx: ToolContext, brand_id: int) -> set[int]:
    ids: set[int] = set()
    for page in range(1, _BRAND_PRODUCT_PAGES + 1):
        result = ctx.xano.search_products(brand=brand_id, page=page, per_page=100)
        ids.update(product.id for product in result.items)
        if page * 100 >= result.total:
            break
    return ids


@mcp.tool(name="catalogai_list_brands", annotations=_read_only("Marques"))
async def list_brands(
    query: Annotated[
        str | None, Field(description="Partie du nom (insensible à la casse)")
    ] = None,
) -> dict[str, Any]:
    """Marques du catalogue Tillin (id et nom), filtrées par nom : retrouver le
    nom exact ou l'id d'une marque."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        wanted = (query or "").strip().casefold()
        brands = [
            {"id": brand.id, "name": brand.name}
            for brand in ctx.xano.list_brands()
            if brand.name and wanted in brand.name.casefold()
        ]
        return {"total": len(brands), "brands": brands[:100]}

    return await run_tool("list_brands", None, work)


# --- Enrichissement -----------------------------------------------------------


def _item_summary(item: ItemPublic) -> dict[str, Any]:
    return {
        "item_id": item.id,
        "product_id": item.tillin_product_id,
        "product_title": item.product_title,
        "status": item.status,
        "source_url": item.source_url,
        "source_method": item.source_method,
        "match_score": item.match_score,
        "proposed_title": item.staged_title,
        "proposed_description": _clip(item.staged_description, 400),
        "proposed_meta": item.staged_meta,
        "proposed_price": item.staged_price,
        "proposed_images": len(item.staged_images_json or []),
        "proposed_weights": len(item.staged_weights_json or []),
        "error": item.error,
    }


@mcp.tool(
    name="catalogai_start_enrichment",
    annotations=_write("Lancer un enrichissement"),
)
async def start_enrichment(
    product_ids: Annotated[
        list[int], Field(min_length=1, max_length=100, description="Ids Tillin")
    ],
    config: Annotated[
        dict[str, Any] | None,
        Field(
            description=(
                "Options facultatives du job (mêmes clés que l'app, ex. "
                "source_url_override pour un seul produit) ; vide = réglages "
                "du compte."
            )
        ),
    ] = None,
) -> dict[str, Any]:
    """Lance l'enrichissement IA de produits (description, meta, titre,
    poids, images depuis le site de la marque). Débite des crédits par fiche
    traitée. Renvoie aussitôt le job : suivez-le avec
    catalogai_get_job_status, puis vérifiez avec catalogai_list_items_to_review."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        background = BackgroundTasks()
        job = job_routes.create_enrichment_job(
            JobCreateRequest(
                selection=JobSelection(ids=product_ids), config=config or {}
            ),
            ctx.db,
            ctx.user,
            background,
            job_runner(),
        )
        _spawn(background)
        per_item = credit_grid(ctx.db, ctx.account_id)["enrich_item"]
        return {
            "job_id": job.id,
            "status": job.status,
            "items": job.counts.total,
            "estimated_credits": job.counts.total * per_item,
        }

    return await run_tool("start_enrichment", "feature_enrich", work)


@mcp.tool(
    name="catalogai_list_enrichments",
    annotations=_read_only("Enrichissements"),
)
async def list_enrichments(
    since: Annotated[
        str | None,
        Field(
            description="Depuis ce jour (AAAA-MM-JJ, today, yesterday) ; vide = tous"
        ),
    ] = None,
    until: Annotated[
        str | None, Field(description="Jusqu'à ce jour inclus (AAAA-MM-JJ)")
    ] = None,
    status: Literal["pending", "processing", "completed", "partial", "failed"]
    | None = None,
    item_status: Annotated[
        Literal["ready_for_review", "approved", "applied", "rejected", "failed"] | None,
        Field(description="Enrichissements ayant au moins une fiche dans cet état"),
    ] = None,
    page: Annotated[int, Field(ge=1)] = 1,
) -> dict[str, Any]:
    """Enrichissements lancés (plus récents d'abord) : statut, nombre de fiches
    par état, date de lancement. Jours en heure de Paris."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        after, before = _day_range(since, until) if since else (None, None)
        result = job_routes.list_jobs(
            ctx.db,
            ctx.user,
            page=page,
            page_size=20,
            status=status,
            item_status=item_status,
            created_after=after,
            created_before=before,
        )
        return {
            "total": result.total,
            "page": page,
            "enrichments": [
                {
                    "job_id": job.id,
                    "status": job.status,
                    "counts": job.counts.model_dump(),
                    "created_at": job.created_at.isoformat(),
                }
                for job in result.items
            ],
        }

    return await run_tool("list_enrichments", "feature_enrich", work)


@mcp.tool(
    name="catalogai_list_enriched_products",
    annotations=_read_only("Fiches enrichies"),
)
async def list_enriched_products(
    since: Annotated[
        str,
        Field(description="Traitées depuis ce jour (AAAA-MM-JJ, today, yesterday)"),
    ] = "today",
    until: Annotated[
        str | None, Field(description="Jusqu'à ce jour inclus (AAAA-MM-JJ)")
    ] = None,
    brand: Annotated[
        str | None, Field(description="Nom de la marque (ex. « Le Petit Souk »)")
    ] = None,
    status: Literal["ready_for_review", "approved", "applied", "rejected", "failed"]
    | None = None,
    limit: Annotated[int, Field(ge=1, le=50)] = 25,
) -> dict[str, Any]:
    """Fiches produits enrichies sur une période (par défaut aujourd'hui, heure
    de Paris), tous enrichissements confondus, filtrables par marque (nom) et
    par statut : ce que l'IA propose et où en est chaque fiche."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        after, before = _day_range(since, until)
        query = (
            select(EnrichmentItem)
            .join(EnrichmentJob, EnrichmentItem.job_id == EnrichmentJob.id)
            .where(
                EnrichmentJob.account_id == ctx.account_id,
                EnrichmentJob.job_type == "enrichment",
                EnrichmentItem.finished_at >= after,
                EnrichmentItem.finished_at < before,
            )
            .order_by(EnrichmentItem.finished_at.desc())
        )
        if status is not None:
            query = query.where(EnrichmentItem.status == status)
        resolved = None
        if brand:
            resolved = _resolve_brand(ctx, brand)
            product_ids = _brand_product_ids(ctx, int(resolved["id"]))
            if not product_ids:
                return {"brand": resolved, "items": [], "truncated": False}
            query = query.where(EnrichmentItem.tillin_product_id.in_(product_ids))
        rows = ctx.db.scalars(query.limit(limit + 1)).all()
        items = [
            {
                **_item_summary(ItemPublic.model_validate(row, from_attributes=True)),
                "job_id": row.job_id,
                "processed_at": row.finished_at.isoformat()
                if row.finished_at
                else None,
            }
            for row in rows[:limit]
        ]
        return {
            "brand": resolved,
            "from": after.isoformat(),
            "to": before.isoformat(),
            "items": items,
            "truncated": len(rows) > limit,
        }

    return await run_tool("list_enriched_products", "feature_enrich", work)


@mcp.tool(
    name="catalogai_get_job_status",
    annotations=_read_only("Suivi d'un enrichissement"),
)
async def get_job_status(job_id: int) -> dict[str, Any]:
    """État d'un enrichissement : statut, compteurs par état des produits
    (à vérifier, validés, appliqués, écartés, échecs) et les échecs récents."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        job = job_routes.read_job(job_id, ctx.db, ctx.user)
        failed = job_routes.list_job_items(
            job_id, ctx.db, ctx.user, status="failed", page=1, page_size=10
        )
        return {
            "job_id": job.id,
            "status": job.status,
            "counts": job.counts.model_dump(),
            "failures": [
                {"item_id": i.id, "product_id": i.tillin_product_id, "error": i.error}
                for i in failed.items
            ],
        }

    return await run_tool("get_job_status", "feature_enrich", work)


@mcp.tool(
    name="catalogai_list_items_to_review",
    annotations=_read_only("Fiches à vérifier"),
)
async def list_items_to_review(
    job_id: int,
    status: Literal["ready_for_review", "approved", "applied", "rejected", "failed"] = (
        "ready_for_review"
    ),
    page: Annotated[int, Field(ge=1)] = 1,
    page_size: Annotated[int, Field(ge=1, le=25)] = 10,
) -> dict[str, Any]:
    """Fiches d'un enrichissement avec ce que l'IA propose (titre,
    description, meta, prix, nombre d'images et de poids, page source)."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        result = job_routes.list_job_items(
            job_id, ctx.db, ctx.user, status=status, page=page, page_size=page_size
        )
        return {
            "total": result.total,
            "page": page,
            "items": [_item_summary(item) for item in result.items],
        }

    return await run_tool("list_items_to_review", "feature_enrich", work)


@mcp.tool(
    name="catalogai_review_item",
    annotations=_write("Valider, écarter ou relancer une fiche"),
)
async def review_item(
    item_id: int, action: Literal["approve", "reject", "retry"]
) -> dict[str, Any]:
    """Décision sur une fiche enrichie : `approve` (validée, prête à
    appliquer), `reject` (écartée, rien n'est écrit), `retry` (relance
    complète du traitement, débite à nouveau des crédits)."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        if action == "approve":
            item = item_routes.approve_item(item_id, ctx.db, ctx.user)
        elif action == "reject":
            item = item_routes.reject_item(item_id, ctx.db, ctx.user)
        else:
            background = BackgroundTasks()
            item = item_routes.retry_item_route(
                item_id, ctx.db, ctx.user, background, job_runner()
            )
            _spawn(background)
        return _item_summary(item)

    return await run_tool("review_item", "feature_enrich", work)


@mcp.tool(
    name="catalogai_apply_item",
    annotations=_write("Appliquer une fiche dans Tillin", destructive=True),
)
async def apply_item(
    item_id: int,
    confirm: Annotated[
        bool, Field(description="false = aperçu seulement ; true = écrit dans Tillin")
    ] = False,
) -> dict[str, Any]:
    """Écrit une fiche VALIDÉE dans Tillin (remplace titre, description,
    meta, prix à 0, poids ; ajoute les images). Sans confirm=true, renvoie
    seulement l'aperçu de ce qui sera écrit."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        if not confirm:
            item = item_routes.read_item(item_id, ctx.db, ctx.user)
            return {
                "preview": True,
                "will_write": _item_summary(item),
                "selected_fields": item.apply_fields_json,
                "note": (
                    "Rien n'a été écrit. Relancez avec confirm=true pour "
                    "appliquer (la fiche doit être validée)."
                ),
            }
        item = item_routes.apply_item_route(item_id, ctx.db, ctx.user, ctx.xano, None)
        return {"applied": item.status == "applied", **_item_summary(item)}

    return await run_tool("apply_item", "feature_enrich", work)


# --- Imports ------------------------------------------------------------------


@mcp.tool(name="catalogai_list_imports", annotations=_read_only("Imports fournisseurs"))
async def list_imports(
    status: Literal["pending", "processing", "completed", "partial", "failed"]
    | None = None,
    item_status: Annotated[
        Literal["ready_for_review", "applied", "rejected", "failed"] | None,
        Field(description="Imports ayant au moins un produit dans cet état"),
    ] = None,
    supplier: str | None = None,
    page: Annotated[int, Field(ge=1)] = 1,
) -> dict[str, Any]:
    """Imports de bons de commande (fichier, fournisseur, statut, produits à
    transférer / transférés, quantités et montants)."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        result = import_routes.list_imports(
            ctx.db,
            ctx.user,
            page=page,
            page_size=20,
            status=status,
            item_status=item_status,
            supplier=supplier,
        )
        return {
            "total": result.total,
            "page": page,
            "imports": [
                {
                    "import_id": job.id,
                    "file": job.file_name,
                    "supplier": job.supplier,
                    "status": job.status,
                    "counts": job.counts.model_dump(),
                    "quantity": job.totals.quantity,
                    "created_at": job.created_at.isoformat(),
                }
                for job in result.items
            ],
        }

    return await run_tool("list_imports", "feature_import", work)


@mcp.tool(
    name="catalogai_get_import_review",
    annotations=_read_only("Produits d'un import"),
)
async def get_import_review(
    import_id: int,
    page: Annotated[int, Field(ge=1)] = 1,
    page_size: Annotated[int, Field(ge=1, le=50)] = 20,
) -> dict[str, Any]:
    """Produits extraits d'un import : référence, titre, marque, variantes,
    quantités, alertes d'extraction, statut (à transférer, transféré…)."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        job = import_routes.read_import(import_id, ctx.db, ctx.user)
        result = import_routes.list_import_items(
            import_id, ctx.db, ctx.user, page=page, page_size=page_size
        )
        return {
            "import_id": job.id,
            "file": job.file_name,
            "supplier": job.supplier,
            "status": job.status,
            "location_id": job.location_id,
            "counts": job.counts.model_dump(),
            "warnings": job.warnings,
            "total": result.total,
            "page": page,
            "products": [
                {
                    "item_id": item.id,
                    "status": item.status,
                    "reference": item.payload.supplier_ref,
                    "title": item.payload.title,
                    "brand": item.payload.brand,
                    "variants": len(item.payload.variants),
                    "quantity": sum(v.quantity or 1 for v in item.payload.variants),
                    "warnings": item.warnings,
                    "tillin_product_id": item.tillin_product_id,
                }
                for item in result.items
            ],
        }

    return await run_tool("get_import_review", "feature_import", work)


@mcp.tool(name="catalogai_list_locations", annotations=_read_only("Magasins Tillin"))
async def list_locations() -> dict[str, Any]:
    """Magasins (emplacements) Tillin de la boutique, pour un transfert
    d'import."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        locations = location_routes.list_locations(ctx.xano)
        return {"locations": [loc.model_dump() for loc in locations]}

    return await run_tool("list_locations", "feature_import", work)


@mcp.tool(
    name="catalogai_transfer_import",
    annotations=_write("Transférer un import vers Tillin", destructive=True),
)
async def transfer_import(
    import_id: int,
    location_id: Annotated[
        int | None, Field(description="Magasin ; vide = celui choisi au dépôt")
    ] = None,
    create_reception: Annotated[
        bool, Field(description="Créer la réception de stock (quantités du bon)")
    ] = True,
    confirm: Annotated[
        bool, Field(description="false = aperçu seulement ; true = crée dans Tillin")
    ] = False,
) -> dict[str, Any]:
    """Crée dans Tillin les produits « à transférer » d'un import (et la
    réception de stock). Non réversible. Sans confirm=true, renvoie seulement
    l'aperçu : nombre de produits, quantités, magasin."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        job = import_routes.read_import(import_id, ctx.db, ctx.user)
        if not confirm:
            return {
                "preview": True,
                "products_to_transfer": job.counts.ready_for_review,
                "already_transferred": job.counts.applied,
                "location_id": location_id or job.location_id,
                "create_reception": create_reception,
                "note": (
                    "Rien n'a été créé. Relancez avec confirm=true pour transférer."
                ),
            }
        result = import_routes.transfer_import(
            import_id,
            ImportTransferRequest(
                location_id=location_id, create_reception=create_reception
            ),
            ctx.db,
            ctx.user,
            ctx.xano,
        )
        return {"transferred": True, **result.model_dump(mode="json")}

    return await run_tool("transfer_import", "feature_import", work)
