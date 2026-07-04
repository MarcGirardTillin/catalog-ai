from typing import Any


def fuzzy(field: Any, value: str) -> Any:
    """
    Create an ILIKE expression from a filter value.

    Supported patterns:
    - '^text' -> starts with
    - '*text' / 'text*' / '*text*' -> wildcard
    - default -> contains
    """
    value = value.strip()
    if value.startswith("^"):
        return field.ilike(f"{value[1:]}%")
    if "*" in value:
        return field.ilike(value.replace("*", "%"))
    return field.ilike(f"%{value}%")
