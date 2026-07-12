"""Image file naming: slugification shared by save-time renames.

Extended by the image-title-template feature (render from product tokens);
for now it carries the slug rules every upload filename goes through.
"""

import re
import unicodedata

# Extensions we strip from user-provided names before re-appending the real
# output extension (avoids "photo.webp.webp").
_KNOWN_EXTENSIONS = ("webp", "jpeg", "jpg", "png")


def slugify_filename(name: str) -> str:
    """ASCII-safe, lowercase, dash-separated file stem ("" when nothing survives)."""
    value = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    return value.strip("-._").lower()


def build_filename(name: str | None, extension: str, *, default_stem: str) -> str:
    """Final upload filename: slugged custom name or the default stem.

    The output extension is imposed (it reflects the encoded format); a
    matching extension already present in `name` is stripped first.
    """
    stem = slugify_filename(name or "")
    for known in _KNOWN_EXTENSIONS:
        if stem.endswith(f".{known}"):
            stem = stem[: -(len(known) + 1)].rstrip("-._")
            break
    if not stem:
        stem = default_stem
    return f"{stem}.{extension}"
