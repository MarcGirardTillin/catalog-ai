"""Tests du prix source (proposé quand le catalogue est à 0 €)."""

from decimal import Decimal

from app.enrich.price import parse_price, source_price


def test_parse_price_handles_common_formats() -> None:
    assert parse_price("990.00") == Decimal("990.00")
    assert parse_price("129,90") == Decimal("129.90")
    assert parse_price("129,90 €") == Decimal("129.90")
    assert parse_price("EUR 1 090") == Decimal("1090")
    assert parse_price("1.090,50") == Decimal("1090.50")
    assert parse_price("1,090.50") == Decimal("1090.50")
    assert parse_price(990) == Decimal("990")
    assert parse_price(Decimal("49.5")) == Decimal("49.5")


def test_parse_price_rejects_absent_or_non_positive() -> None:
    assert parse_price(None) is None
    assert parse_price("") is None
    assert parse_price("gratuit") is None
    assert parse_price("0") is None
    assert parse_price(0) is None


def test_source_price_prefers_the_single_variant_price() -> None:
    source = {
        "variants": [{"price": "990.00"}, {"price": "990.00"}],
        "_price": "129,90 €",
    }
    assert source_price(source) == Decimal("990.00")


def test_source_price_ambiguous_variants_yield_none() -> None:
    # Prix différents entre variantes (soldes partielles…) : pas de proposition.
    assert source_price({"variants": [{"price": "990"}, {"price": "790"}]}) is None


def test_source_price_falls_back_to_the_page_price() -> None:
    assert source_price({"variants": [], "_price": "129,90 €"}) == Decimal("129.90")
    assert source_price({"variants": []}) is None
    assert source_price(None) is None


def test_source_price_refuses_non_euro_currencies() -> None:
    # Page /gb en livres (vécu dedicatedbrand 2026-08-22) : jamais proposé.
    assert source_price({"_price": "39.95", "_currency": "GBP"}) is None
    assert source_price({"_price": "39.95", "_currency": "EUR"}) is not None
    # Devise inconnue : comportement historique (proposé).
    assert source_price({"_price": "39.95"}) is not None
