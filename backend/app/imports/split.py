"""Split multi-color extracted products into one product per color.

The extractor reconciles document lines by supplier reference, which merges
colorways into variants of a single product (the Tillin default model). Some
boutiques want ONE SHEET PER COLOR instead (`ImportProfileConfig.
split_by_color`): this module re-expands those products at staging time, so
downstream (review grid, credits, CSV, transfer) simply sees more products.

Le suffixe ajouté à la référence est PERSONNALISABLE par profil (validé Marc
2026-07-30) :
- forme : nom de la couleur (défaut), initiale(s), ou aucun suffixe (les
  fiches partagent alors la même référence — les titres différencient) ;
- séparateur : « - » (défaut), espace, ou rien (« 48814BLK » évite que la
  recherche plein-texte Xano, qui découpe sur les tirets, fasse ressortir
  d'autres produits contenant la couleur).
Variants without a color keep the original reference, unsuffixed.
"""

import re

from app.imports.schema import ImportedProduct

SuffixMode = str  # "color" | "initial" | "none" (Literal du schéma de profil)


def _clean_color(color: str, joiner: str) -> str:
    """ "Dark Olive" -> "DARK-OLIVE" (reference-safe, joiner configurable)."""
    return (
        re.sub(r"[^A-Za-z0-9]+", "\x00", color.strip())
        .strip("\x00")
        .upper()
        .replace("\x00", joiner)
    )


def _initial_suffixes(colors: list[str]) -> dict[str, str]:
    """Initiale de chaque couleur, étendue jusqu'à unicité (Bleu/Blanc → BL/BLA…).

    L'extension s'arrête au nom complet nettoyé si deux couleurs restent
    indistinguables (cas dégénéré : même nom).
    """
    cleaned = {color: _clean_color(color, "") for color in colors}
    length = 1
    while length <= max((len(v) for v in cleaned.values()), default=1):
        candidates = {color: value[:length] for color, value in cleaned.items()}
        if len(set(candidates.values())) == len(candidates):
            return candidates
        length += 1
    return cleaned


def split_products_by_color(
    products: list[ImportedProduct],
    *,
    suffix_mode: str = "color",
    separator: str = "-",
) -> list[ImportedProduct]:
    """One product per distinct variant color; single-color products pass through.

    Variant order is preserved inside each group, and groups come out in the
    order their color first appears in the document.
    """
    out: list[ImportedProduct] = []
    for product in products:
        colors: list[str] = []
        for variant in product.variants:
            color = (variant.color or "").strip()
            if color not in colors:
                colors.append(color)
        real_colors = [color for color in colors if color]
        if len(real_colors) <= 1:
            out.append(product)
            continue
        initials = _initial_suffixes(real_colors) if suffix_mode == "initial" else {}
        for color in colors:
            variants = [v for v in product.variants if (v.color or "").strip() == color]
            if suffix_mode == "none" or not color:
                suffix = ""
            elif suffix_mode == "initial":
                suffix = initials.get(color, "")
            elif suffix_mode == "code":
                # Code couleur fournisseur (Marc 2026-08-22) ; repli sur le
                # nom quand le document n'en portait pas.
                code = next(
                    (
                        (v.color_code or "").strip()
                        for v in product.variants
                        if (v.color or "").strip() == color
                        and (v.color_code or "").strip()
                    ),
                    "",
                )
                suffix = code.upper() or _clean_color(color, separator or "")
            else:
                # Le nom de couleur interne suit le même séparateur que la
                # jonction réf-couleur (« REF DARK OLIVE », « REFDARKOLIVE »).
                suffix = _clean_color(color, separator or "")
            out.append(
                product.model_copy(
                    update={
                        "supplier_ref": (
                            f"{product.supplier_ref}{separator}{suffix}"
                            if suffix
                            else product.supplier_ref
                        ),
                        "variants": variants,
                    }
                )
            )
    return out
