"""prepare_upload : ce que Xano rejetait silencieusement ne sort plus d'ici."""

import io

import pytest
from PIL import Image

from app.api.exceptions import AppException
from app.imaging.uploads import prepare_upload


def _image_bytes(image_format: str, size: tuple[int, int] = (12, 10)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buffer, format=image_format)
    return buffer.getvalue()


def test_jpeg_passes_through_untouched() -> None:
    data = _image_bytes("JPEG")
    name, payload, media_type = prepare_upload("photo.jpg", data)
    assert (name, payload, media_type) == ("photo.jpg", data, "image/jpeg")


def test_png_and_webp_keep_their_format() -> None:
    png = _image_bytes("PNG")
    assert prepare_upload("shot.png", png) == ("shot.png", png, "image/png")
    webp = _image_bytes("WEBP")
    assert prepare_upload("shot.webp", webp) == ("shot.webp", webp, "image/webp")


def test_missing_extension_gets_the_real_one() -> None:
    # Xano jette les fichiers sans extension (200 + images: []).
    name, _, media_type = prepare_upload("photo", _image_bytes("JPEG"))
    assert (name, media_type) == ("photo.jpg", "image/jpeg")


def test_lying_extension_is_corrected_to_the_real_format() -> None:
    name, _, media_type = prepare_upload("capture.jpg", _image_bytes("PNG"))
    assert (name, media_type) == ("capture.png", "image/png")


def test_heic_iphone_photo_is_converted_to_jpeg() -> None:
    heic = _image_bytes("HEIF")  # décodeur enregistré par prepare_upload
    name, payload, media_type = prepare_upload("IMG_0042.HEIC", heic)
    assert (name, media_type) == ("IMG_0042.jpg", "image/jpeg")
    with Image.open(io.BytesIO(payload)) as converted:
        assert converted.format == "JPEG"


def test_exotic_name_is_sanitized_and_blank_name_gets_a_default() -> None:
    name, _, _ = prepare_upload("C:\\photos\\été 2026 (1).jpg", _image_bytes("JPEG"))
    assert name == "t-2026-1.jpg"
    fallback, _, _ = prepare_upload(None, _image_bytes("JPEG"), index=2)
    assert fallback == "image-3.jpg"


def test_non_image_is_rejected_with_a_clear_error() -> None:
    with pytest.raises(AppException) as excinfo:
        prepare_upload("notes.pdf", b"%PDF-1.4 not an image")
    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "not_an_image"
