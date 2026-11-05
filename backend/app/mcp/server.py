"""Outils MCP CatalogAI : catalogue, enrichissements, imports.

Les outils réutilisent les fonctions de route de l'API (mêmes contrôles :
scoping, crédits, états autorisés) sous la garde commune `run_tool`
(utilisateur du jeton, module du compte). Réponses compactes et paginées ;
les actions qui écrivent dans Tillin (`apply_item`, `transfer_import`)
renvoient un APERÇU tant que `confirm` n'est pas vrai.
"""

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import MultiAuth
from mcp.types import ToolAnnotations
from pydantic import Field
from sqlalchemy import select

from app.api.deps import get_job_runner, get_photoroom_client
from app.api.exceptions import AppException
from app.api.routes import brands as brand_routes
from app.api.routes import imaging as imaging_routes
from app.api.routes import imports as import_routes
from app.api.routes import items as item_routes
from app.api.routes import jobs as job_routes
from app.api.routes import locations as location_routes
from app.api.schemas import AssetSaveRequest, NormalizeOptions
from app.api.schemas.brands import BrandWebsiteUrlsUpdate
from app.api.schemas.enrichment import ItemPublic, JobCreateRequest, JobSelection
from app.api.schemas.imports import ImportTransferRequest
from app.api.services.credits import balance as credit_balance
from app.api.services.credits import credit_grid, require_credits
from app.api.services.imaging import (
    account_settings,
    merged_normalize_options,
    output_files,
    run_normalize,
)
from app.clients.base import NotConfiguredError
from app.clients.xano import XanoError, normalize_website_urls
from app.core.db import SessionLocal
from app.imaging.naming import render_image_filename
from app.mcp.auth import ApiTokenVerifier
from app.mcp.guard import ToolContext, run_tool
from app.mcp.oauth import CatalogOAuthProvider
from app.mcp.uploads import (
    STUDIO_FILE_TTL,
    UPLOAD_TTL,
    UploadGrant,
    sign_studio_file,
    sign_upload,
    studio_file_url,
    upload_url,
)
from app.models import (
    Account,
    EnrichmentItem,
    EnrichmentJob,
    ImageAsset,
    InstructionTemplate,
)

logger = logging.getLogger("app.mcp")

INSTRUCTIONS = (
    "CatalogAI (Tillin) : catalogue produits d'une boutique, enrichissement des "
    "fiches par IA, imports de bons de commande fournisseurs. Commencez par "
    "catalogai_get_account_overview pour connaître les modules actifs et le "
    "solde de crédits. Les traitements longs (enrichissement) renvoient un "
    "identifiant : suivez-les avec catalogai_get_job_status. Les actions qui "
    "écrivent dans Tillin demandent confirm=true après un aperçu."
)

# OAuth 2.1 (connecteur claude.ai, `codex mcp login`) + jetons personnels
# (Claude Code, Codex avec bearer) : le premier qui reconnaît le jeton gagne.
mcp = FastMCP(
    name="CatalogAI",
    instructions=INSTRUCTIONS,
    auth=MultiAuth(server=CatalogOAuthProvider(), verifiers=[ApiTokenVerifier()]),
)

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
    stocks = [
        v.stock_quantity for v in product.variants if v.stock_quantity is not None
    ]
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
        # Somme des variantes ; None = stock inconnu (aucune variante suivie).
        "stock": sum(stocks) if stocks else None,
        # Connexions e-commerce (« Shopify »…) ; vide = non connecté.
        "origins": list(product.origins),
    }


_STATUS_CODES = {"inactive": "1", "active": "2", "archived": "3"}
# Codes Xano natifs : 2 connectés, 3 partiellement, 4 non connectés.
_ECOMMERCE_CODES = {"connected": 2, "partial": 3, "not_connected": 4}


def _resolve_classification(ctx: ToolContext, group: str, label: str, name: str) -> int:
    """Id d'une valeur de classification (fournisseur, tag, saison) par son
    nom : exact, sinon unique contenant ; erreur listant les candidates."""
    wanted = name.strip().casefold()
    options = [
        o for o in ctx.xano.get_classification().get(group, []) if o.get("title")
    ]
    exact = [o for o in options if str(o["title"]).casefold() == wanted]
    matches = exact or [o for o in options if wanted in str(o["title"]).casefold()]
    if len(matches) == 1:
        return int(matches[0]["id"])
    if not matches:
        raise ToolError(f"Aucun {label} « {name} » dans le catalogue.")
    names = ", ".join(sorted(str(o["title"]) for o in matches)[:10])
    raise ToolError(f"Plusieurs {label}s correspondent à « {name} » : {names}.")


def _studio_processed(
    ctx: ToolContext, product_id: int | None = None
) -> dict[int, Any]:
    """Images Tillin créées par un enregistrement Studio -> date du traitement."""
    query = select(ImageAsset.tillin_image_ids_json, ImageAsset.finished_at).where(
        ImageAsset.account_id == ctx.account_id,
        ImageAsset.tillin_image_ids_json.is_not(None),
    )
    if product_id is not None:
        query = query.where(ImageAsset.product_id == product_id)
    processed: dict[int, Any] = {}
    for image_ids, finished_at in ctx.db.execute(query).all():
        for image_id in image_ids or []:
            if image_id is not None:
                processed[int(image_id)] = finished_at
    return processed


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
    supplier: Annotated[
        str | None, Field(description="Filtre fournisseur par son NOM")
    ] = None,
    tag: Annotated[
        str | None, Field(description="Filtre tag par son NOM (ex. « Outlet »)")
    ] = None,
    season: Annotated[
        str | None, Field(description="Filtre saison par son NOM (ex. « A/W 26 »)")
    ] = None,
    status: Annotated[
        Literal["active", "inactive", "archived"] | None,
        Field(description="Statut du produit dans Tillin (vide = tous)"),
    ] = None,
    ecommerce: Annotated[
        Literal["connected", "partial", "not_connected"] | None,
        Field(description="Connexion e-commerce (vide = toutes)"),
    ] = None,
    ecommerce_site: Annotated[
        str | None,
        Field(
            description=(
                "Ne garder que les produits reliés à ce site (ex. « Shopify ») ; "
                "filtre appliqué à la page renvoyée"
            )
        ),
    ] = None,
    page: Annotated[int, Field(ge=1)] = 1,
    per_page: Annotated[int, Field(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    """Recherche dans le catalogue Tillin de la boutique (résumé par produit :
    id, titre, référence, marque, prix, couleurs, nombre d'images, stock total
    des variantes, connexions e-commerce `origins` — vide = non synchronisé).
    Filtres : marque (nom ou id), fournisseur, tag, saison (par leur nom),
    statut, connexion e-commerce, site e-commerce ; jusqu'à 100 produits par
    page."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        wanted = brand_id
        if wanted is None and brand:
            wanted = int(_resolve_brand(ctx, brand)["id"])
        filters: dict[str, Any] = {}
        for group, label, name, key in (
            ("suppliers", "fournisseur", supplier, "supplier"),
            ("tags", "tag", tag, "tag"),
            ("seasons", "saison", season, "season"),
        ):
            if name:
                filters[key] = _resolve_classification(ctx, group, label, name)
        if status:
            filters["status"] = _STATUS_CODES[status]
        if ecommerce:
            filters["ecommerce"] = _ECOMMERCE_CODES[ecommerce]
        result = ctx.xano.search_products(
            text=query, brand=wanted, page=page, per_page=per_page, **filters
        )
        items = result.items
        response: dict[str, Any] = {"total": result.total, "page": page}
        if ecommerce_site:
            site = ecommerce_site.strip().casefold()
            kept = [p for p in items if site in {o.casefold() for o in p.origins}]
            response["site_filtered_out"] = len(items) - len(kept)
            items = kept
        response["products"] = [_product_summary(p) for p in items]
        return response

    return await run_tool("search_products", None, work)


@mcp.tool(name="catalogai_get_product", annotations=_read_only("Fiche produit"))
async def get_product(product_id: int) -> dict[str, Any]:
    """Fiche d'un produit Tillin : description, variantes (code-barres,
    couleur, taille, prix, stock), images (image_id, position, date de
    traitement Studio si déjà traitée) et connexions e-commerce."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        product = ctx.xano.get_product(product_id)
        if product is None:
            raise AppException(
                status_code=404, code="not_found", message="Produit introuvable"
            )
        processed = _studio_processed(ctx, product_id)
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
            "images": [
                {
                    "image_id": image.id,
                    "url": image.url,
                    "position": image.position,
                    # Image issue d'un traitement Studio enregistré (date du
                    # traitement) ; None = jamais traitée par le Studio.
                    "studio_processed_at": (
                        processed[image.id].isoformat()
                        if image.id in processed and processed[image.id]
                        else None
                    ),
                }
                for image in product.images[:30]
            ],
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
    # Bornes rendues en UTC : comme les horodatages stockés (la base de test
    # compare en texte — une borne +02:00 y décalait le jour entre 0 h et 2 h).
    start = datetime.combine(_day(since), time.min, PARIS).astimezone(UTC)
    if until is None:
        return start, datetime.now(UTC) + timedelta(seconds=1)
    end = datetime.combine(_day(until), time.min, PARIS) + timedelta(days=1)
    return start, end.astimezone(UTC)


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
    """Marques du catalogue Tillin (id, nom, sites de référence), filtrées par
    nom : retrouver le nom exact ou l'id d'une marque, et voir les sites où
    l'enrichissement cherche ses fiches."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        wanted = (query or "").strip().casefold()
        brands = [
            {"id": brand.id, "name": brand.name, "website_urls": brand.website_urls}
            for brand in ctx.xano.list_brands()
            if brand.name and wanted in brand.name.casefold()
        ]
        return {"total": len(brands), "brands": brands[:100]}

    return await run_tool("list_brands", None, work)


_MAX_BRAND_URLS = 20


def _clean_brand_urls(urls: list[str]) -> list[str]:
    cleaned = normalize_website_urls(urls)
    invalid = [
        url
        for url in cleaned
        if not url.lower().startswith(("http://", "https://"))
        or "." not in url.split("://", 1)[1]
    ]
    if invalid:
        raise ToolError(f"URL invalides : {', '.join(invalid[:5])}")
    return cleaned


def _url_key(url: str) -> str:
    return url.split("://", 1)[-1].casefold()


@mcp.tool(
    name="catalogai_set_brand_websites",
    annotations=_write("Modifier les sites d'une marque", destructive=True),
)
async def set_brand_websites(
    brand: Annotated[
        str | None, Field(description="Marque par son NOM (ou utilisez brand_id)")
    ] = None,
    brand_id: Annotated[int | None, Field(description="Marque (id Tillin)")] = None,
    add: Annotated[
        list[str] | None, Field(description="URLs à ajouter aux sites existants")
    ] = None,
    remove: Annotated[
        list[str] | None, Field(description="URLs à retirer des sites existants")
    ] = None,
    replace_with: Annotated[
        list[str] | None,
        Field(description="Remplace TOUTE la liste ; [] vide la liste"),
    ] = None,
    confirm: Annotated[
        bool, Field(description="false = aperçu seulement ; true = écrit dans Tillin")
    ] = False,
) -> dict[str, Any]:
    """Ajoute, retire ou remplace les sites de référence d'une marque (20 max),
    ceux où l'enrichissement cherche les fiches produits. Sans confirm=true,
    renvoie seulement l'aperçu avant / après. Modifier une URL : remove
    l'ancienne et add la nouvelle. Vaut pour les prochains enrichissements."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        if replace_with is not None and (add or remove):
            raise ToolError("replace_with ne se combine pas avec add ou remove.")
        if replace_with is None and not add and not remove:
            raise ToolError("Précisez add, remove ou replace_with.")
        if (brand is None) == (brand_id is None):
            raise ToolError("Précisez la marque : brand (nom) OU brand_id.")
        # La marque doit être dans le catalogue du compte : un id d'une autre
        # boutique est refusé avant toute écriture.
        wanted = brand_id
        if wanted is None:
            wanted = int(_resolve_brand(ctx, str(brand))["id"])
        target = next((b for b in ctx.xano.list_brands() if b.id == wanted), None)
        if target is None:
            raise ToolError(
                f"Marque {wanted} absente de ce catalogue : voir catalogai_list_brands."
            )

        before = list(target.website_urls)
        if replace_with is not None:
            after = _clean_brand_urls(replace_with)
        else:
            gone = {_url_key(url) for url in normalize_website_urls(remove or [])}
            missing = gone - {_url_key(url) for url in before}
            if missing:
                raise ToolError(
                    f"URLs à retirer absentes de la marque : {sorted(missing)[:5]}"
                )
            after = [url for url in before if _url_key(url) not in gone]
            after += _clean_brand_urls(add or [])
        # Dédoublonné en gardant la première occurrence, dans l'ordre.
        unique: dict[str, str] = {}
        for url in after:
            unique.setdefault(_url_key(url), url)
        after = list(unique.values())
        if len(after) > _MAX_BRAND_URLS:
            raise ToolError(f"{_MAX_BRAND_URLS} sites maximum par marque.")

        change = {
            "brand_id": wanted,
            "brand": target.name,
            "before": before,
            "after": after,
        }
        if not confirm:
            return {
                **change,
                "preview": True,
                "note": "Rien n'a été écrit. Relancez avec confirm=true.",
            }
        brand_routes.update_brand_website_urls(
            wanted, BrandWebsiteUrlsUpdate(website_urls=after), ctx.xano
        )
        return {**change, "updated": True}

    return await run_tool("set_brand_websites", "feature_enrich", work, write=True)


# --- Poids par catégorie --------------------------------------------------------
# Poids par défaut (page Boutique de l'app) : utilisés à l'application d'une
# fiche et au transfert d'un import quand aucun poids source n'existe. Réservés
# aux comptes qui ont l'import ou l'enrichissement, comme l'écran de l'app.


def _require_weight_modules(ctx: ToolContext) -> None:
    if ctx.user.is_admin:
        return
    settings = account_settings(ctx.db, ctx.account_id)
    if not (settings.feature_import or settings.feature_enrich):
        raise ToolError(
            "Le module import ou enrichissement doit être activé pour gérer les "
            "poids par catégorie."
        )


@mcp.tool(
    name="catalogai_list_category_weights",
    annotations=_read_only("Poids par catégorie"),
)
async def list_category_weights(
    query: Annotated[
        str | None, Field(description="Partie du nom (insensible à la casse)")
    ] = None,
) -> dict[str, Any]:
    """Catégories Tillin de la boutique et leur poids par défaut en kg (0 = non
    renseigné). Ce poids s'applique à l'application d'une fiche et au transfert
    d'un import quand aucun poids source n'existe. Il ne modifie pas les
    produits déjà en boutique."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        _require_weight_modules(ctx)
        wanted = (query or "").strip().casefold()
        categories = [
            {
                "category_id": category["id"],
                "title": category["title"],
                "default_weight_kg": category.get("default_weight_kg") or 0,
            }
            for category in ctx.xano.get_classification().get("categories", [])
            if category.get("visible", True)
            and wanted in str(category["title"]).casefold()
        ]
        return {"total": len(categories), "categories": categories}

    return await run_tool("list_category_weights", None, work)


@mcp.tool(
    name="catalogai_set_category_weights",
    annotations=_write("Modifier les poids par catégorie", destructive=True),
)
async def set_category_weights(
    weights: Annotated[
        dict[str, float],
        Field(
            min_length=1,
            max_length=100,
            description=(
                'Poids par défaut en KILOGRAMMES par catégorie : {"<category_id>": '
                "0.25} ; 0 = effacer. Ids : catalogai_list_category_weights"
            ),
        ),
    ],
    confirm: Annotated[
        bool, Field(description="false = aperçu seulement ; true = écrit dans Tillin")
    ] = False,
) -> dict[str, Any]:
    """Modifie le poids par défaut (kg) d'une ou plusieurs catégories. Sans
    confirm=true, renvoie seulement l'aperçu (avant / après). Vaut pour les
    prochaines fiches appliquées et les prochains imports : les produits déjà
    en boutique ne changent pas."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        _require_weight_modules(ctx)
        wanted: dict[int, float] = {}
        for key, weight in weights.items():
            try:
                wanted[int(key)] = float(weight)
            except (TypeError, ValueError) as exc:
                raise ToolError(
                    f"weights : la clé « {key} » n'est pas un id de catégorie."
                ) from exc
        invalid = sorted(i for i, weight in wanted.items() if not 0 <= weight < 1000)
        if invalid:
            raise ToolError(
                f"Poids invalides pour les catégories {invalid[:10]} : attendu "
                "en kg, de 0 à moins de 1000."
            )
        categories = {
            int(category["id"]): category
            for category in ctx.xano.get_classification().get("categories", [])
        }
        unknown = sorted(set(wanted) - set(categories))
        if unknown:
            raise ToolError(
                f"Catégories inconnues : {unknown[:10]} — voir "
                "catalogai_list_category_weights."
            )
        changes = [
            {
                "category_id": category_id,
                "title": categories[category_id]["title"],
                "before_kg": categories[category_id].get("default_weight_kg") or 0,
                "after_kg": weight,
            }
            for category_id, weight in wanted.items()
        ]
        if not confirm:
            return {
                "preview": True,
                "will_write": changes,
                "note": "Rien n'a été écrit. Relancez avec confirm=true.",
            }
        updated, failed = [], []
        for change in changes:
            category = categories[int(change["category_id"])]
            try:
                ctx.xano.set_category_default_weight(
                    int(change["category_id"]),
                    float(change["after_kg"]),
                    title=str(category["title"]),
                    parent_id=category.get("parent_id"),
                    visible=category.get("visible", True),
                )
            except XanoError as exc:
                failed.append({**change, "error": exc.message})
            else:
                updated.append(change)
        return {"updated": updated, "failed": failed}

    return await run_tool("set_category_weights", None, work, write=True)


# --- Studio (traitement d'image de base) ------------------------------------------
# Mêmes briques que le Studio de l'app : un actif `normalize` par image
# (détourage, fond, ratio, marges, centrage, format, qualité, poids), crédit
# `image_process` débité au succès, enregistrement par la route « save » en
# mode remplacement. Un « job » MCP = les actifs portant le même
# `params_json.mcp_job` (pas de table dédiée). Module studio requis.

_STUDIO_FETCH_WORKERS = 6


def _job_assets_query(ctx: ToolContext, job_id: str) -> Any:
    return (
        select(ImageAsset)
        .where(
            ImageAsset.account_id == ctx.account_id,
            ImageAsset.params_json["mcp_job"].as_string() == job_id,
        )
        .order_by(ImageAsset.id)
    )


def _studio_targets(
    ctx: ToolContext,
    product_ids: list[int],
    image_ids: list[int] | None,
    skip_processed: bool,
) -> dict[str, Any]:
    """Images à traiter (produit, image, URL, position) + exclusions."""
    ids = list(dict.fromkeys(product_ids))
    with ThreadPoolExecutor(max_workers=_STUDIO_FETCH_WORKERS) as pool:
        products = list(pool.map(ctx.xano.get_product, ids))
    processed = _studio_processed(ctx) if skip_processed else {}
    wanted = set(image_ids or [])
    seen: set[int] = set()
    targets: list[dict[str, Any]] = []
    already: list[dict[str, Any]] = []
    missing = [pid for pid, product in zip(ids, products, strict=True) if not product]
    for pid, product in zip(ids, products, strict=True):
        if product is None:
            continue
        for image in product.images:
            if image.id is None or image.id in seen:
                continue
            if wanted and image.id not in wanted:
                continue
            seen.add(image.id)
            entry = {
                "product_id": pid,
                "image_id": image.id,
                "url": image.url,
                "position": image.position,
            }
            if image.id in processed:
                already.append(entry)
            else:
                targets.append(entry)
    unknown = sorted(wanted - seen)
    if unknown:
        raise ToolError(
            f"Images absentes des fiches indiquées : {unknown[:10]} — relisez-les "
            "avec catalogai_get_product."
        )
    return {"targets": targets, "already_processed": already, "missing": missing}


def _run_studio_job(
    jobs: list[tuple[int, str]],
    options: NormalizeOptions,
    photoroom: Any,
    account_id: int,
    unit_cost: int,
) -> None:
    """Traite les images d'un job À LA SUITE (un fil, pas 300 en parallèle).

    Le solde est revérifié avant chaque image : d'autres traitements du
    compte peuvent l'avoir entamé depuis le lancement.
    """
    for asset_id, url in jobs:
        try:
            with SessionLocal() as db:
                if credit_balance(db, account_id) < unit_cost:
                    asset = db.get(ImageAsset, asset_id)
                    if asset is not None:
                        asset.status = "failed"
                        asset.error = "Crédits insuffisants"
                        asset.finished_at = datetime.now(UTC)
                        db.commit()
                    continue
            run_normalize(asset_id, url, options, photoroom)
        except Exception:  # noqa: BLE001 — une image ne bloque pas le job
            logger.exception("studio job: asset %s failed", asset_id)


# Remplaçable dans les tests (pas de vrai traitement d'image).
studio_job_runner = _run_studio_job


def _start_studio_thread(*args: Any) -> None:
    threading.Thread(
        target=studio_job_runner, args=args, name="mcp-studio", daemon=True
    ).start()


@mcp.tool(
    name="catalogai_studio_process_images",
    annotations=_write("Lancer un traitement Studio"),
)
async def studio_process_images(
    product_ids: Annotated[
        list[int], Field(min_length=1, max_length=100, description="Ids Tillin")
    ],
    image_ids: Annotated[
        list[int] | None,
        Field(
            description=(
                "Images à traiter (image_id de catalogai_get_product) ; vide = "
                "toutes les images des fiches"
            )
        ),
    ] = None,
    settings: Annotated[
        NormalizeOptions | None,
        Field(
            description=(
                "Réglages facultatifs ; chaque champ absent prend le réglage "
                "Studio du compte. remove_bg (détourage), bg_color (hex, ex. "
                "e4e4e4), ratio (4:5, 1:1, 3:4, 16:9, original), center, "
                "margin_percent (0-45), format (webp, jpeg, png), quality "
                "(1-100), max_kb (poids max du fichier)"
            )
        ),
    ] = None,
    skip_processed: Annotated[
        bool,
        Field(description="true = ignorer les images déjà issues du Studio"),
    ] = True,
    dry_run: Annotated[
        bool,
        Field(description="true = compter images et crédits sans rien lancer"),
    ] = False,
) -> dict[str, Any]:
    """Traitement d'image de base du Studio (détourage, fond, ratio, marges,
    centrage, format, qualité, poids) sur les images de fiches produits. Les
    résultats restent EN ATTENTE : rien n'est écrit dans Tillin. dry_run=true
    donne le nombre d'images et de crédits sans rien lancer. Sinon renvoie un
    job_id : suivez-le avec catalogai_get_studio_job, puis appliquez avec
    catalogai_apply_studio_result."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        found = _studio_targets(ctx, product_ids, image_ids, skip_processed)
        targets = found["targets"]
        options = merged_normalize_options(ctx.db, ctx.account_id, settings)
        unit_cost = credit_grid(ctx.db, ctx.account_id)["image_process"]
        balance = credit_balance(ctx.db, ctx.account_id)
        summary: dict[str, Any] = {
            "images": len(targets),
            "estimated_credits": len(targets) * unit_cost,
            "credits_balance": balance,
            "skipped_already_processed": len(found["already_processed"]),
            "products_not_found": found["missing"],
            "settings": options.model_dump(),
        }
        if dry_run:
            return {**summary, "dry_run": True}
        if not targets:
            raise ToolError("Aucune image à traiter sur ces fiches.")
        require_credits(ctx.db, ctx.account_id, len(targets) * unit_cost)
        # Le prestataire est résolu AVANT toute écriture (clé absente = refus net).
        try:
            photoroom = get_photoroom_client()
        except NotConfiguredError as exc:
            raise ToolError(
                "Le traitement d'image est indisponible (Photoroom)."
            ) from exc
        job_id = uuid.uuid4().hex[:12]
        assets = [
            ImageAsset(
                account_id=ctx.account_id,
                product_id=target["product_id"],
                verb="normalize",
                provider="photoroom" if options.remove_bg else "local",
                status="pending",
                source_image=target["url"],
                source_product_image_id=target["image_id"],
                params_json={
                    "options": options.model_dump(),
                    "mcp_job": job_id,
                    "launched_by": ctx.user.id,
                },
            )
            for target in targets
        ]
        ctx.db.add_all(assets)
        ctx.db.commit()
        jobs = [(asset.id, str(asset.source_image)) for asset in assets]
        _start_studio_thread(jobs, options, photoroom, ctx.account_id, unit_cost)
        return {**summary, "job_id": job_id, "status": "pending"}

    return await run_tool(
        "studio_process_images", "feature_studio", work, write=not dry_run
    )


def _asset_view(asset: ImageAsset) -> dict[str, Any]:
    outputs = output_files(asset)
    output = outputs[0] if outputs else {}
    saved = asset.tillin_image_ids_json
    processed_url = None
    if asset.status == "completed" and output and saved is None:
        processed_url = studio_file_url(sign_studio_file(asset.id, asset.account_id))
    return {
        "asset_id": asset.id,
        "product_id": asset.product_id,
        "image_id": asset.source_product_image_id,
        "source_url": asset.source_image,
        "status": "applied" if saved is not None else asset.status,
        "processed_url": processed_url,
        "width": output.get("width"),
        "height": output.get("height"),
        "format": output.get("format"),
        "size_bytes": output.get("bytes"),
        "error": asset.error,
        "tillin_image_ids": saved,
    }


@mcp.tool(
    name="catalogai_get_studio_job",
    annotations=_read_only("Suivi d'un traitement Studio"),
)
async def get_studio_job(job_id: str) -> dict[str, Any]:
    """État d'un traitement Studio et, pour chaque image : id et URL
    d'origine, URL de l'image traitée (publique 24 h, pour la mesurer avant
    de valider), dimensions, statut, erreur."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        assets = list(ctx.db.scalars(_job_assets_query(ctx, job_id)).all())
        if not assets:
            raise AppException(
                status_code=404, code="not_found", message="Job Studio introuvable"
            )
        images = [_asset_view(asset) for asset in assets]
        counts: dict[str, int] = {}
        for image in images:
            counts[image["status"]] = counts.get(image["status"], 0) + 1
        running = counts.get("pending", 0) + counts.get("processing", 0)
        return {
            "job_id": job_id,
            "status": "processing" if running else "completed",
            "counts": counts,
            "links_valid_hours": int(STUDIO_FILE_TTL.total_seconds() // 3600),
            "images": images,
        }

    return await run_tool("get_studio_job", "feature_studio", work)


@mcp.tool(
    name="catalogai_apply_studio_result",
    annotations=_write("Appliquer un traitement Studio", destructive=True),
)
async def apply_studio_result(
    job_id: Annotated[
        str | None, Field(description="Job Studio (ou utilisez product_id)")
    ] = None,
    product_id: Annotated[
        int | None,
        Field(description="Toutes les images traitées en attente d'une fiche"),
    ] = None,
    confirm: Annotated[
        bool, Field(description="false = aperçu seulement ; true = écrit dans Tillin")
    ] = False,
) -> dict[str, Any]:
    """Remplace dans Tillin chaque image d'origine par sa version traitée, à
    la même position dans la galerie, et désactive l'originale. Sans
    confirm=true, renvoie seulement l'aperçu. Seules les images traitées
    par catalogai_studio_process_images et pas encore appliquées comptent."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        if (job_id is None) == (product_id is None):
            raise ToolError("Précisez job_id OU product_id.")
        if job_id is not None:
            query = _job_assets_query(ctx, job_id)
        else:
            query = (
                select(ImageAsset)
                .where(
                    ImageAsset.account_id == ctx.account_id,
                    ImageAsset.product_id == product_id,
                    ImageAsset.params_json["mcp_job"].as_string().is_not(None),
                )
                .order_by(ImageAsset.id)
            )
        candidates = [
            asset
            for asset in ctx.db.scalars(query).all()
            if asset.status == "completed"
            and asset.tillin_image_ids_json is None
            and asset.source_product_image_id is not None
        ]
        # Une image traitée deux fois : la plus récente l'emporte.
        latest: dict[int, ImageAsset] = {}
        for asset in candidates:
            latest[int(asset.source_product_image_id or 0)] = asset
        products: dict[int, Any] = {}
        for asset in latest.values():
            if asset.product_id not in products:
                products[asset.product_id] = ctx.xano.get_product(asset.product_id)
        template = (
            account_settings(ctx.db, ctx.account_id).image_title_template or ""
        ).strip()
        plan: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for source_id, asset in latest.items():
            product = products.get(asset.product_id)
            position = next(
                (
                    i.position
                    for i in (product.images if product else [])
                    if i.id == source_id
                ),
                None,
            )
            if product is None or position is None:
                skipped.append(
                    {
                        "asset_id": asset.id,
                        "image_id": source_id,
                        "reason": "image d'origine absente de la fiche",
                    }
                )
                continue
            plan.append(
                {
                    "asset_id": asset.id,
                    "product_id": asset.product_id,
                    "replaces_image_id": source_id,
                    "position": position,
                    "processed_url": _asset_view(asset)["processed_url"],
                }
            )
        if not confirm:
            return {
                "preview": True,
                "will_replace": plan,
                "skipped": skipped,
                "note": "Rien n'a été écrit. Relancez avec confirm=true.",
            }
        applied: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for step in plan:
            name = None
            if template:
                try:
                    stem = render_image_filename(
                        products[step["product_id"]], int(step["position"]), template
                    )
                except ValueError:
                    stem = ""
                name = stem or None
            try:
                result = imaging_routes.save_asset(
                    int(step["asset_id"]),
                    AssetSaveRequest(replace=True, filenames=[name] if name else None),
                    ctx.db,
                    ctx.user,
                    ctx.xano,
                )
            except AppException as exc:
                ctx.db.rollback()
                failed.append({**step, "error": exc.message})
                continue
            applied.append(
                {
                    **step,
                    "new_image_ids": [i.id for i in result.images if i.id is not None],
                }
            )
        return {"applied": applied, "failed": failed, "skipped": skipped}

    return await run_tool("apply_studio_result", "feature_studio", work, write=True)


# --- Images produit -------------------------------------------------------------
# Mêmes endpoints Tillin que l'app (ajout en masse, désactivation, positions),
# sans module requis — comme l'upload de la fiche produit dans l'app.

_MAX_IMAGES_PER_CALL = 20


def _require_product(ctx: ToolContext, product_id: int) -> Any:
    product = ctx.xano.get_product(product_id)
    if product is None:
        raise AppException(
            status_code=404, code="not_found", message="Produit introuvable"
        )
    return product


def _gallery(product: Any) -> list[dict[str, Any]]:
    return [
        {"image_id": image.id, "url": image.url, "position": image.position}
        for image in product.images
        if image.id is not None
    ]


@mcp.tool(
    name="catalogai_create_image_upload",
    annotations=_write("Préparer l'envoi d'images locales"),
)
async def create_image_upload(
    product_id: int,
    filenames: Annotated[
        list[str],
        Field(
            min_length=1,
            max_length=_MAX_IMAGES_PER_CALL,
            description="Noms des fichiers locaux à envoyer (ex. packshot-1.jpg)",
        ),
    ],
) -> dict[str, Any]:
    """Prépare l'ajout d'images STOCKÉES SUR L'ORDINATEUR à une fiche produit :
    renvoie une URL d'envoi par fichier, valable 30 minutes. Envoyez chaque
    fichier avec `curl -sS -X PUT --data-binary @<fichier> "<upload_url>"` :
    la réponse JSON donne l'image créée (image_id, url hébergée) ou l'erreur
    (format, poids : 15 Mo max ; JPEG, PNG, WEBP, HEIC). Les images s'ajoutent
    en fin de galerie : réordonnez ou remplacez ensuite avec
    catalogai_arrange_product_images. Images accessibles en ligne : utilisez
    plutôt catalogai_add_product_images."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        _require_product(ctx, product_id)
        uploads = []
        for name in filenames:
            clean = name.strip().replace("\\", "/").rsplit("/", 1)[-1] or "image.jpg"
            token = sign_upload(
                UploadGrant(
                    user_id=ctx.user.id,
                    account_id=ctx.account_id,
                    product_id=product_id,
                    filename=clean[:200],
                )
            )
            uploads.append({"filename": clean, "upload_url": upload_url(token)})
        return {
            "product_id": product_id,
            "expires_in_minutes": int(UPLOAD_TTL.total_seconds() // 60),
            "method": "PUT, corps = octets bruts du fichier",
            "uploads": uploads,
        }

    return await run_tool("create_image_upload", None, work, write=True)


@mcp.tool(
    name="catalogai_add_product_images",
    annotations=_write("Ajouter des images depuis des URLs"),
)
async def add_product_images(
    product_id: int,
    image_urls: Annotated[
        list[str],
        Field(
            min_length=1,
            max_length=_MAX_IMAGES_PER_CALL,
            description="URLs publiques des images (http/https)",
        ),
    ],
) -> dict[str, Any]:
    """Ajoute à une fiche des images accessibles en ligne : Tillin les
    télécharge et les héberge, en fin de galerie. Renvoie les images créées
    et les URLs que Tillin n'a pas pu récupérer. Réordonner ou remplacer :
    catalogai_arrange_product_images."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        urls = [u.strip() for u in image_urls if u.strip()]
        invalid = [u for u in urls if not u.lower().startswith(("http://", "https://"))]
        if invalid:
            raise ToolError(f"URL non http(s) : {', '.join(invalid[:5])}")
        _require_product(ctx, product_id)
        created = ctx.xano.add_product_images(product_id, urls)
        # L'endpoint Tillin avale les échecs (200 avec une liste amputée) :
        # sans correspondance fiable URL → image, on signale le manque.
        return {
            "product_id": product_id,
            "requested": len(urls),
            "created": [{"image_id": i.id, "url": i.url} for i in created],
            "not_created": max(len(urls) - len(created), 0),
        }

    return await run_tool("add_product_images", None, work, write=True)


@mcp.tool(
    name="catalogai_arrange_product_images",
    annotations=_write("Ordonner / remplacer les images", destructive=True),
)
async def arrange_product_images(
    product_id: int,
    image_ids: Annotated[
        list[int],
        Field(
            min_length=1,
            description=(
                "Ids des images dans l'ordre voulu (la 1re devient l'image "
                "principale) ; ids visibles dans catalogai_get_product ou au "
                "retour d'un ajout"
            ),
        ),
    ],
    remove_others: Annotated[
        bool,
        Field(
            description=(
                "true = « remplacer » : les images non listées sont retirées "
                "de la fiche ; false = elles restent, après les listées"
            )
        ),
    ] = False,
    confirm: Annotated[
        bool,
        Field(description="false = aperçu seulement ; true = écrit dans Tillin"),
    ] = False,
) -> dict[str, Any]:
    """Réordonne la galerie d'une fiche et, avec remove_others=true, retire
    les images non listées (remplacement). Sans confirm=true, renvoie
    seulement l'aperçu. Les images retirées sont désactivées dans Tillin."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        product = _require_product(ctx, product_id)
        current = [image.id for image in product.images if image.id is not None]
        unknown = [i for i in image_ids if i not in current]
        if unknown:
            raise ToolError(
                f"Images inconnues sur cette fiche : {unknown[:10]} — relisez-la "
                "avec catalogai_get_product."
            )
        wanted = list(dict.fromkeys(image_ids))
        others = [i for i in current if i not in wanted]
        removed = others if remove_others else []
        order = wanted if remove_others else wanted + others
        if not confirm:
            return {
                "preview": True,
                "order": order,
                "will_remove": removed,
                "note": "Rien n'a été écrit. Relancez avec confirm=true.",
            }
        if removed:
            ctx.xano.deactivate_product_images(removed)
        ctx.xano.set_product_image_positions(
            [(image_id, position) for position, image_id in enumerate(order, start=1)]
        )
        updated = ctx.xano.get_product(product_id) or product
        return {
            "product_id": product_id,
            "removed": removed,
            "images": _gallery(updated),
        }

    return await run_tool("arrange_product_images", None, work, write=True)


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
        # Information qui a rapproché la fiche : barcode / reference / title.
        "matched_by": (item.resolution_json or {}).get("matched_by"),
        "proposed_title": item.staged_title,
        "proposed_description": _clip(item.staged_description, 400),
        "proposed_meta": item.staged_meta,
        "proposed_price": item.staged_price,
        "proposed_images": len(item.staged_images_json or []),
        "proposed_weights": len(item.staged_weights_json or []),
        "error": item.error,
    }


# Clés de `config` acceptées depuis le MCP : celles que l'app envoie au
# lancement (panneau d'options) et les réglages par défaut du compte que
# l'utilisateur peut déjà modifier. Le reste (modèle d'IA, lanceur, profils
# d'import…) n'est pas un choix client : refusé plutôt qu'ignoré.
CONFIG_KEYS: dict[str, str] = {
    "editorial_instructions": (
        "texte libre : consignes de rédaction (remplace le prompt)"
    ),
    "seo_keywords": "liste de mots-clés SEO à placer dans le texte",
    "extra_website_urls": (
        "liste d'URLs de sites où chercher la fiche, en plus du site de la marque"
    ),
    "source_url_override": (
        "URL de la page produit à utiliser (un seul produit par job)"
    ),
    "transforms": (
        "objet {copy, meta, title, weights, images} de booléens : false = ne "
        "pas générer cet élément (absent = tout générer)"
    ),
    "scrape": "objet {online: false} : aucune recherche en ligne (texte seul)",
    "image": (
        "objet {auto_normalize: true} : traiter les images (réglages Studio du "
        "compte, module studio requis, crédits image en plus)"
    ),
    "title_template": (
        "modèle de titre, ex. « {title} - {brand} » (défaut : réglage du compte)"
    ),
    "title_case": "casse du titre : none, upper, capitalize, title, sentence",
    "client_context": (
        "contexte boutique ajouté aux consignes (défaut : réglage du compte)"
    ),
    "meta_max_length": "longueur max de la meta description, 50 à 320 (défaut 160)",
    "content_language": "langue du texte, code ISO (défaut fr)",
    "keep_product_names": "false = le texte peut reformuler le nom du produit",
}
_TRANSFORM_KEYS = ("copy", "meta", "title", "weights", "images")


def _checked_config(config: dict[str, Any] | None) -> dict[str, Any]:
    checked = dict(config or {})
    if "instruction_id" in checked:
        raise ToolError(
            "Choisissez le prompt avec prompt_id (ou prompts), pas dans config."
        )
    unknown = sorted(set(checked) - set(CONFIG_KEYS))
    if unknown:
        raise ToolError(
            f"Clés de config inconnues : {', '.join(unknown)}. Clés possibles : "
            f"{', '.join(CONFIG_KEYS)}."
        )
    transforms = checked.get("transforms")
    if transforms is not None and (
        not isinstance(transforms, dict) or set(transforms) - set(_TRANSFORM_KEYS)
    ):
        raise ToolError(
            f"transforms : objet de booléens parmi {', '.join(_TRANSFORM_KEYS)}."
        )
    return checked


def _account_prompt_ids(ctx: ToolContext) -> set[int]:
    return set(
        ctx.db.scalars(
            select(InstructionTemplate.id).where(
                InstructionTemplate.account_id == ctx.account_id
            )
        ).all()
    )


@mcp.tool(
    name="catalogai_list_prompts", annotations=_read_only("Prompts d'enrichissement")
)
async def list_prompts() -> dict[str, Any]:
    """Prompts (instructions de rédaction) de la bibliothèque du compte : id,
    nom, catégories Tillin visées (le prompt s'y applique d'office quand
    aucun n'est choisi) et début du texte. À passer en prompt_id ou prompts
    dans catalogai_start_enrichment."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        rows = ctx.db.scalars(
            select(InstructionTemplate)
            .where(InstructionTemplate.account_id == ctx.account_id)
            .order_by(
                InstructionTemplate.position.is_(None),
                InstructionTemplate.position,
                InstructionTemplate.name,
            )
        ).all()
        return {
            "total": len(rows),
            "prompts": [
                {
                    "prompt_id": row.id,
                    "name": row.name,
                    "categories": [str(c) for c in row.categories_json or []],
                    "excerpt": _clip(row.content, 300),
                }
                for row in rows
            ],
            "default_rule": (
                "Sans prompt choisi : consignes par défaut du compte si elles "
                "existent, sinon le prompt rattaché à la catégorie Tillin de "
                "chaque produit."
            ),
        }

    return await run_tool("list_prompts", "feature_enrich", work)


@mcp.tool(
    name="catalogai_start_enrichment",
    annotations=_write("Lancer un enrichissement"),
)
async def start_enrichment(
    product_ids: Annotated[
        list[int], Field(min_length=1, max_length=100, description="Ids Tillin")
    ],
    prompt_id: Annotated[
        int | None,
        Field(description="Prompt pour tous les produits (catalogai_list_prompts)"),
    ] = None,
    prompts: Annotated[
        dict[str, int] | None,
        Field(
            description=(
                'Prompt PAR PRODUIT : {"<product_id>": <prompt_id>} ; les '
                "produits absents prennent prompt_id (ou la règle par défaut). "
                "Un job est créé par prompt."
            )
        ),
    ] = None,
    config: Annotated[
        dict[str, Any] | None,
        Field(
            description=(
                "Options facultatives (vide = réglages du compte). Clés : "
                + " ; ".join(f"{key} — {text}" for key, text in CONFIG_KEYS.items())
            )
        ),
    ] = None,
) -> dict[str, Any]:
    """Lance l'enrichissement IA de produits (description, meta, titre,
    poids, images depuis le site de la marque). Débite des crédits par fiche
    traitée. Avec des prompts différents par produit, un job par prompt.
    Renvoie aussitôt le ou les jobs : suivez-les avec catalogai_get_job_status,
    puis vérifiez avec catalogai_list_items_to_review."""

    def work(ctx: ToolContext) -> dict[str, Any]:
        base_config = _checked_config(config)
        per_product: dict[int, int] = {}
        for key, value in (prompts or {}).items():
            try:
                per_product[int(key)] = int(value)
            except (TypeError, ValueError) as exc:
                raise ToolError(
                    f"prompts : la clé « {key} » n'est pas un id produit."
                ) from exc
        strays = sorted(set(per_product) - set(product_ids))
        if strays:
            raise ToolError(
                f"prompts cite des produits hors product_ids : {strays[:10]}"
            )
        # Tout est vérifié AVANT la première écriture (prompts du compte,
        # crédits de l'ensemble) : jamais de lancement partiel.
        wanted = {p for p in [prompt_id, *per_product.values()] if p is not None}
        missing = sorted(wanted - _account_prompt_ids(ctx))
        if missing:
            raise ToolError(
                f"Prompts introuvables sur ce compte : {missing} — voir "
                "catalogai_list_prompts."
            )
        groups: dict[int | None, list[int]] = {}
        for product_id in dict.fromkeys(product_ids):
            group = per_product.get(product_id, prompt_id)
            groups.setdefault(group, []).append(product_id)
        per_item = credit_grid(ctx.db, ctx.account_id)["enrich_item"]
        require_credits(
            ctx.db, ctx.account_id, sum(map(len, groups.values())) * per_item
        )

        jobs: list[dict[str, Any]] = []
        for group_prompt, ids in groups.items():
            job_config = dict(base_config)
            if group_prompt is not None:
                job_config["instruction_id"] = group_prompt
            background = BackgroundTasks()
            job = job_routes.create_enrichment_job(
                JobCreateRequest(selection=JobSelection(ids=ids), config=job_config),
                ctx.db,
                ctx.user,
                background,
                job_runner(),
            )
            _spawn(background)
            jobs.append(
                {
                    "job_id": job.id,
                    "prompt_id": group_prompt,
                    "status": job.status,
                    "items": job.counts.total,
                }
            )
        total = sum(int(job["items"]) for job in jobs)
        result: dict[str, Any] = {"jobs": jobs, "estimated_credits": total * per_item}
        if len(jobs) == 1:
            result.update(
                job_id=jobs[0]["job_id"], status=jobs[0]["status"], items=total
            )
        return result

    return await run_tool("start_enrichment", "feature_enrich", work, write=True)


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

    return await run_tool("review_item", "feature_enrich", work, write=True)


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

    return await run_tool("apply_item", "feature_enrich", work, write=True)


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

    return await run_tool("transfer_import", "feature_import", work, write=True)
