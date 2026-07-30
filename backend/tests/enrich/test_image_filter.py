"""Tests du filtre d'images stagees et du complement JSON-LD pauvre."""

from app.enrich.pipeline import _is_junk_image_url


def test_junk_image_urls_are_detected() -> None:
    """Placeholders lazy-load et miniatures video ne sont pas des visuels
    produit (vecu eu.patagonia.com : 1x1.png Demandware + miniature YouTube)."""
    junk = [
        "https://eu.patagonia.com/on/demandware.static/-/default/dw05/images/1x1.png",
        "https://i.ytimg.com/vi/Y19Vd0r73qE/maxresdefault.jpg",
        "https://www.youtube.com/img/thumb.jpg",
        "https://cdn.site.com/assets/placeholder.jpg",
        "https://cdn.site.com/img/spacer.gif",
        "https://cdn.site.com/sprites/sprite-icons.png",
    ]
    for url in junk:
        assert _is_junk_image_url(url), url


def test_real_product_images_pass_the_filter() -> None:
    real = [
        "https://cdn.shopify.com/s/files/1/img/product-123.jpg",
        "https://www.jacquemus.com/dw/image/v2/x/26HDRW00925_06.jpg?q=100",
        # « pixel » dans le NOM DE DOMAINE ne doit pas filtrer.
        "https://pixelstore.example/products/robe.jpg",
    ]
    for url in real:
        assert not _is_junk_image_url(url), url


def test_upgrade_image_url_boosts_cdn_thumbnails() -> None:
    """Miniatures Cloudinary h_147 → h_1600 (vérifié live img1.g-star.com)."""
    from app.enrich.pipeline import _upgrade_image_url

    thumb = (
        "https://img1.g-star.com/product/c_fill,f_auto,h_147,q_80/"
        "v177/D28627-E360-001-M01/jeans.jpg"
    )
    assert "h_1600" in _upgrade_image_url(thumb)
    # Hors segment de transformation : URL intacte.
    plain = "https://cdn.example.com/images/h_147/photo.jpg"
    assert _upgrade_image_url(plain) == plain
    # Déjà grande : intacte (h_2000 ne matche pas 1-3 chiffres).
    big = "https://img1.g-star.com/product/c_fill,f_auto,h_2000,q_80/v1/x.jpg"
    assert _upgrade_image_url(big) == big
