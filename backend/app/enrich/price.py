"""Prix de vente lu sur la page source — proposé quand le catalogue n'en a pas.

Trois formes selon le chemin de résolution : les variantes du JSON Shopify
(`variants[].price`, décimal en texte), le `_price` du JSON-LD (offers) ou de
l'extraction Firecrawl (texte libre : « 129,90 € », « EUR 1 090 »…). Le
parsing accepte les formats français et anglais ; tout prix non strictement
positif est ignoré (l'endpoint enrich Xano ignore aussi le 0, vérifié live).
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Any

# Un nombre avec séparateurs de milliers (espace, fine, point) et décimales
# (virgule ou point) : « 1 090 », « 1.090,50 », « 129.90 », « 129,90 ».
_NUMBER_PATTERN = re.compile(r"\d{1,3}(?:[  .,]\d{3})*(?:[.,]\d{1,2})?|\d+")


def parse_price(value: Any) -> Decimal | None:
    """Best-effort: a positive Decimal price out of a raw source value."""
    if value is None:
        return None
    if isinstance(value, int | float | Decimal):
        try:
            price = Decimal(str(value))
        except InvalidOperation:  # pragma: no cover - inf/nan
            return None
        return price if price > 0 else None
    text = str(value).strip()
    if not text:
        return None
    match = _NUMBER_PATTERN.search(text)
    if match is None:
        return None
    raw = match.group()
    # Le DERNIER séparateur suivi de 1-2 chiffres est la marque décimale ;
    # tout autre séparateur est un séparateur de milliers.
    raw = raw.replace(" ", "").replace(" ", "")
    last_dot, last_comma = raw.rfind("."), raw.rfind(",")
    decimal_sep = max(last_dot, last_comma)
    if decimal_sep != -1 and len(raw) - decimal_sep - 1 <= 2:
        integer = re.sub(r"[.,]", "", raw[:decimal_sep])
        raw = f"{integer}.{raw[decimal_sep + 1 :]}"
    else:
        raw = re.sub(r"[.,]", "", raw)
    try:
        price = Decimal(raw)
    except InvalidOperation:
        return None
    return price if price > 0 else None


def source_price(source_product: dict[str, Any] | None) -> Decimal | None:
    """The source page's selling price, or None when it carries none.

    Variant prices win (Shopify JSON, authoritative) ; sinon le `_price`
    extrait de la page (JSON-LD/Firecrawl). Des variantes à prix différents
    (soldes partielles…) rendent la proposition ambiguë → None.
    """
    if not source_product:
        return None
    # Garde-fou devise (Marc 2026-08-22, page /gb en £ de dedicatedbrand) :
    # un prix affiché dans une autre devise que l'euro n'est JAMAIS proposé —
    # « 39,95 » £ écrit tel quel dans Tillin serait faux. Devise inconnue =
    # on propose (comportement historique, sites FR majoritaires).
    currency = str(source_product.get("_currency") or "").strip().upper()
    if currency and currency != "EUR":
        return None
    prices = {
        price
        for variant in source_product.get("variants") or []
        if isinstance(variant, dict)
        and (price := parse_price(variant.get("price"))) is not None
    }
    if len(prices) == 1:
        return next(iter(prices))
    if prices:
        return None
    return parse_price(source_product.get("_price"))
