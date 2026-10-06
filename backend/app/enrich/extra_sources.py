"""Fiches source supplémentaires « par couleur » d'un item d'enrichissement.

Un produit Tillin à plusieurs couleurs peut avoir UNE fiche par couleur sur
le site de la marque (ex. peluche déclinée en deux coloris, deux URLs). La
fiche principale (``item.source_url``) reste l'autorité pour la copie, la
meta, le titre, le prix et les poids ; chaque fiche supplémentaire n'apporte
que ses IMAGES, taguées avec la couleur du produit qu'elle illustre.

Contrat de stockage (colonnes JSON libres, aucune migration) :

- ``resolution_json["extra_sources"]`` = ``[{"url", "color", "title"?}]`` ;
- ``resolution_json["main_color"]`` = couleur de la fiche principale (option) ;
- une entrée de ``staged_images_json`` issue d'une fiche supplémentaire porte
  ``color`` + ``source_page`` (URL de la fiche) ; une entrée de la fiche
  principale porte ``color`` seulement quand ``main_color`` est renseignée.

Les fonctions ici sont pures (aucun réseau) : la récupération de la page
vit dans ``EnrichmentPipeline.stage_extra_source``.
"""

from typing import Any

from app.models import EnrichmentItem


def extra_sources(item: EnrichmentItem) -> list[dict[str, Any]]:
    """Les fiches supplémentaires de l'item (copie défensive)."""
    raw = (item.resolution_json or {}).get("extra_sources")
    if not isinstance(raw, list):
        return []
    return [dict(s) for s in raw if isinstance(s, dict) and s.get("url")]


def extra_source_urls(item: EnrichmentItem) -> set[str]:
    return {str(s["url"]) for s in extra_sources(item)}


def _entries(item: EnrichmentItem) -> list[dict[str, Any]]:
    return [dict(e) for e in (item.staged_images_json or []) if isinstance(e, dict)]


def _renumber(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for position, entry in enumerate(entries, start=1):
        entry["position"] = position
    return entries


def _identities(entry: dict[str, Any]) -> set[str]:
    """URLs qui désignent la même image (normalisée : fichier + original)."""
    return {str(v) for v in (entry.get("url"), entry.get("source_url")) if v}


def _set_resolution(item: EnrichmentItem, **changes: Any) -> None:
    resolution = dict(item.resolution_json or {})
    for key, value in changes.items():
        if value is None or value == []:
            resolution.pop(key, None)
        else:
            resolution[key] = value
    item.resolution_json = resolution


def _update_selection(
    item: EnrichmentItem, *, removed: set[str], added: list[str]
) -> None:
    """Fait suivre la sélection partielle d'apply (``image_urls``), si elle
    existe : retire les images supprimées, ajoute les nouvelles."""
    apply_fields = dict(item.apply_fields_json or {})
    selected = apply_fields.get("image_urls")
    if not isinstance(selected, list):
        return
    kept = [u for u in selected if u not in removed]
    apply_fields["image_urls"] = kept + [u for u in added if u not in kept]
    item.apply_fields_json = apply_fields


def add_extra_source(
    item: EnrichmentItem,
    *,
    url: str,
    color: str,
    title: str | None,
    image_urls: list[str],
) -> list[int]:
    """Associe (ou remplace) une fiche supplémentaire et stage ses images.

    Les images sont ajoutées EN FIN de galerie, dédupliquées contre les
    images déjà stagées des autres fiches. Une URL déjà associée remplace ses
    images et sa couleur. Retourne les ``asset_id`` d'images normalisées
    retirées (staging à purger par l'appelant après commit).
    """
    entries = _entries(item)
    removed_entries = [e for e in entries if e.get("source_page") == url]
    kept_entries = [e for e in entries if e.get("source_page") != url]
    known: set[str] = set()
    for entry in kept_entries:
        known |= _identities(entry)
    added: list[str] = []
    for image_url in image_urls:
        if image_url not in known and image_url not in added:
            added.append(image_url)
    new_entries = kept_entries + [
        {"url": u, "position": 0, "color": color, "source_page": url} for u in added
    ]
    item.staged_images_json = _renumber(new_entries) or None

    sources = [s for s in extra_sources(item) if s.get("url") != url]
    source: dict[str, Any] = {"url": url, "color": color}
    if title:
        source["title"] = title
    sources.append(source)
    _set_resolution(item, extra_sources=sources)

    removed_urls = {str(e.get("url")) for e in removed_entries} - set(added)
    _update_selection(item, removed=removed_urls, added=added)
    return [int(e["asset_id"]) for e in removed_entries if e.get("asset_id")]


def remove_extra_source(item: EnrichmentItem, url: str) -> list[int]:
    """Retire une fiche supplémentaire et ses images (et de la sélection).

    Raises LookupError quand l'URL n'est pas une fiche associée. Retourne les
    ``asset_id`` d'images normalisées retirées (staging à purger).
    """
    sources = extra_sources(item)
    if not any(s.get("url") == url for s in sources):
        raise LookupError(f"{url} is not an extra source of this item")
    entries = _entries(item)
    removed_entries = [e for e in entries if e.get("source_page") == url]
    kept = [e for e in entries if e.get("source_page") != url]
    item.staged_images_json = _renumber(kept) or None
    _set_resolution(
        item, extra_sources=[s for s in sources if s.get("url") != url] or None
    )
    _update_selection(
        item, removed={str(e.get("url")) for e in removed_entries}, added=[]
    )
    return [int(e["asset_id"]) for e in removed_entries if e.get("asset_id")]


def _tag_main_entries(item: EnrichmentItem, color: str | None) -> None:
    extras = extra_source_urls(item)
    entries = _entries(item)
    for entry in entries:
        if entry.get("source_page") in extras:
            continue
        if color:
            entry["color"] = color
        else:
            entry.pop("color", None)
    if entries:
        item.staged_images_json = entries


def set_main_color(item: EnrichmentItem, color: str | None) -> None:
    """Couleur de la fiche principale : stockée et taguée sur ses images."""
    color = (color or "").strip() or None
    _set_resolution(item, main_color=color)
    _tag_main_entries(item, color)


def main_color(item: EnrichmentItem) -> str | None:
    value = (item.resolution_json or {}).get("main_color")
    return str(value) if value else None


def snapshot_extras(
    item: EnrichmentItem,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    """(fiches, entrées d'images des fiches, couleur principale) — à
    capturer AVANT un re-staging de la fiche principale."""
    urls = extra_source_urls(item)
    extra_entries = [e for e in _entries(item) if e.get("source_page") in urls]
    return extra_sources(item), extra_entries, main_color(item)


def restore_extras(
    item: EnrichmentItem,
    snapshot: tuple[list[dict[str, Any]], list[dict[str, Any]], str | None],
) -> None:
    """Après un changement de fiche principale : les images de la nouvelle
    fiche d'abord (taguées ``main_color``), puis celles des fiches
    supplémentaires, dédupliquées. Une fiche supplémentaire devenue la
    fiche principale est retirée de la liste."""
    sources, extra_entries, color = snapshot
    main_url = item.source_url
    promoted = next((s for s in sources if s.get("url") == main_url), None)
    if promoted is not None and promoted.get("color"):
        # La fiche promue garde sa couleur, désormais celle de la principale.
        color = str(promoted["color"])
    sources = [s for s in sources if s.get("url") != main_url]
    urls = {str(s["url"]) for s in sources}
    extra_entries = [e for e in extra_entries if e.get("source_page") in urls]
    main_entries = [e for e in _entries(item) if e.get("source_page") not in urls]
    for entry in main_entries:
        entry.pop("source_page", None)
        if color:
            entry["color"] = color
        else:
            entry.pop("color", None)
    known: set[str] = set()
    for entry in main_entries:
        known |= _identities(entry)
    merged = list(main_entries)
    for entry in extra_entries:
        if _identities(entry) & known:
            continue
        known |= _identities(entry)
        merged.append(entry)
    item.staged_images_json = _renumber(merged) or None
    _set_resolution(item, extra_sources=sources or None, main_color=color)
