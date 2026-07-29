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
