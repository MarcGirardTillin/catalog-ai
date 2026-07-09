"""Optional parse-only tests on real supplier files (never any API call).

The `everyday-tasks/` folder is git-ignored and absent in CI, so these
tests are skipped whenever the files are missing.
"""

import re
from pathlib import Path

import pytest

from app.imports.parsers import parse_file

_EVERYDAY = Path(__file__).resolve().parents[3] / "everyday-tasks"
LESPION_XLSX = (
    _EVERYDAY / "integration LEspion" / "pdfs traites" / "2026-06-30-19037114-Y-s.xlsx"
)
LTDC_XLSX = (
    _EVERYDAY
    / "integration Bambinoh"
    / "Le Temps Des Cerises"
    / "Commande BAMB3201 - 02359226.xlsx"
)

_EAN13 = re.compile(r"^\d{13}$")


def _parse_cells(path: Path) -> list[str]:
    document = parse_file(path.read_bytes(), path.name)
    assert document.kind == "tabular"
    assert document.tables, "expected at least one sheet"
    cells = [
        cell.strip() for table in document.tables for row in table.rows for cell in row
    ]
    assert any(cells), "expected non-empty cells"
    return cells


@pytest.mark.skipif(not LESPION_XLSX.exists(), reason="everyday-tasks not present")
def test_real_lespion_xlsx_parses() -> None:
    # JOOR order export: no EAN column, but the PO number must survive
    # parsing as an exact digit string (it is stored as a number in Excel).
    cells = _parse_cells(LESPION_XLSX)
    assert "19037114" in cells


@pytest.mark.skipif(not LTDC_XLSX.exists(), reason="everyday-tasks not present")
def test_real_le_temps_des_cerises_xlsx_parses() -> None:
    cells = _parse_cells(LTDC_XLSX)
    eans = [cell for cell in cells if _EAN13.match(cell)]
    assert eans, "expected at least one 13-digit EAN-looking cell"
