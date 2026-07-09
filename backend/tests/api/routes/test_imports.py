"""Tests for the supplier-file import routes (/imports)."""

from collections.abc import Generator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db, get_import_runner
from app.core.config import settings
from app.main import app
from app.models import Account, EnrichmentJob, ImportItem


@pytest.fixture
def upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Store uploads in an isolated temp directory for the test."""
    target = tmp_path / "uploads"
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(target))
    return target


@pytest.fixture
def import_client(
    auth_client: TestClient,
    upload_dir: Path,  # noqa: ARG001 — activates the temp upload dir
) -> Generator[TestClient]:
    """Authenticated client with a no-op import runner (overridable per test)."""
    app.dependency_overrides[get_import_runner] = lambda: lambda job_id: None
    yield auth_client
    app.dependency_overrides.pop(get_import_runner, None)


def _upload(
    client: TestClient, name: str = "commande.pdf", data: bytes = b"%PDF-1.4 fake"
) -> dict[str, Any]:
    response = client.post("/imports", files={"file": (name, data)})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _db() -> Any:
    return next(app.dependency_overrides[get_db]())


def test_imports_require_authentication(client: TestClient, upload_dir: Path) -> None:
    assert client.get("/imports").status_code == 401
    assert (
        client.post("/imports", files={"file": ("commande.pdf", b"%PDF")}).status_code
        == 401
    )
    assert not upload_dir.exists()  # nothing was stored


def test_upload_creates_import_job_and_stores_file(
    import_client: TestClient, upload_dir: Path
) -> None:
    # Uppercase extension: accepted (case-insensitive), stored lowercased.
    job = _upload(import_client, name="Commande L'Espion.PDF", data=b"%PDF-1.4 espion")

    assert job["status"] == "pending"
    assert job["file_name"] == "Commande L'Espion.PDF"
    assert job["counts"] == {"total": 0, "ready_for_review": 0, "failed": 0}
    assert job["warnings"] == []
    assert job["error"] is None
    assert job["started_at"] is None
    assert job["duration_seconds"] is None

    stored = list(upload_dir.iterdir())
    assert len(stored) == 1
    # Generated name (uuid + extension) — never the hostile original name.
    assert stored[0].suffix == ".pdf"
    assert stored[0].name != "Commande L'Espion.PDF"
    assert stored[0].read_bytes() == b"%PDF-1.4 espion"

    # The job records both names.
    db = _db()
    row = db.get(EnrichmentJob, job["id"])
    assert row.job_type == "import"
    assert row.selection_json == {
        "file_name": "Commande L'Espion.PDF",
        "file_path": str(stored[0]),
    }


def test_upload_schedules_background_runner(
    import_client: TestClient, upload_dir: Path
) -> None:
    seen: list[int] = []
    app.dependency_overrides[get_import_runner] = lambda: seen.append

    job = _upload(import_client)

    assert seen == [job["id"]]
    assert len(list(upload_dir.iterdir())) == 1


def test_upload_rejects_unsupported_extension(import_client: TestClient) -> None:
    for name in ("virus.exe", "notes.txt", "archive.pdf.zip", "sansextension"):
        response = import_client.post("/imports", files={"file": (name, b"x")})
        assert response.status_code == 422, name
        assert response.json()["code"] == "unsupported_file_type"


def test_upload_rejects_files_over_20mb(
    import_client: TestClient, upload_dir: Path
) -> None:
    too_big = b"0" * (20 * 1024 * 1024 + 1)
    response = import_client.post("/imports", files={"file": ("gros.csv", too_big)})
    assert response.status_code == 413
    assert response.json()["code"] == "file_too_large"
    assert not upload_dir.exists()  # rejected before being stored


def test_list_and_detail_imports(import_client: TestClient) -> None:
    first = _upload(import_client, name="a.csv", data=b"ref;ean\n")
    second = _upload(import_client, name="b.xlsx", data=b"PK fake")

    listing = import_client.get("/imports")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 2
    # Newest first.
    assert [job["id"] for job in body["items"]] == [second["id"], first["id"]]
    assert body["items"][0]["file_name"] == "b.xlsx"

    detail = import_client.get(f"/imports/{first['id']}")
    assert detail.status_code == 200
    assert detail.json()["file_name"] == "a.csv"

    assert import_client.get("/imports/99999").status_code == 404


def test_import_detail_surfaces_warnings_error_and_counts(
    import_client: TestClient,
) -> None:
    job = _upload(import_client)

    db = _db()
    row = db.get(EnrichmentJob, job["id"])
    row.status = "completed"
    row.config_json = {
        "warnings": ["colonne prix ambiguë"],
        "document": {"po_number": "PO-889", "supplier": "L'Espion"},
    }
    db.add_all(
        [
            ImportItem(
                job_id=row.id,
                account_id=row.account_id,
                payload_json={"supplier_ref": "REF-1"},
            ),
            ImportItem(
                job_id=row.id,
                account_id=row.account_id,
                status="failed",
                payload_json={"supplier_ref": "REF-2"},
                error="EAN illisible",
            ),
        ]
    )
    db.commit()

    detail = import_client.get(f"/imports/{job['id']}").json()
    assert detail["counts"] == {"total": 2, "ready_for_review": 1, "failed": 1}
    assert detail["warnings"] == ["colonne prix ambiguë"]
    assert detail["po_number"] == "PO-889"
    assert detail["supplier"] == "L'Espion"

    row.config_json = {"error": "ValueError: unreadable"}
    db.commit()
    assert (
        import_client.get(f"/imports/{job['id']}").json()["error"]
        == "ValueError: unreadable"
    )


def test_list_import_items(import_client: TestClient) -> None:
    job = _upload(import_client)

    db = _db()
    row = db.get(EnrichmentJob, job["id"])
    db.add_all(
        [
            ImportItem(
                job_id=row.id,
                account_id=row.account_id,
                payload_json={"supplier_ref": "REF-1", "title": "Pull marin"},
                warnings_json=["prix douteux"],
            ),
            ImportItem(
                job_id=row.id,
                account_id=row.account_id,
                payload_json={"supplier_ref": "REF-2"},
            ),
        ]
    )
    db.commit()

    listing = import_client.get(f"/imports/{job['id']}/items")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 2
    assert [i["payload"]["supplier_ref"] for i in body["items"]] == ["REF-1", "REF-2"]
    assert body["items"][0]["status"] == "ready_for_review"
    assert body["items"][0]["warnings"] == ["prix douteux"]
    assert body["items"][1]["warnings"] == []
    assert body["items"][0]["error"] is None

    assert import_client.get("/imports/99999/items").status_code == 404


def test_import_detail_totals_sum_quantity_and_amounts(
    import_client: TestClient,
) -> None:
    job = _upload(import_client)
    assert job["totals"] == {
        "quantity": 0,
        "wholesale_amount": None,
        "retail_amount": None,
    }
    # Not extracted yet: no document-level facts either.
    assert job["po_number"] is None
    assert job["supplier"] is None

    db = _db()
    row = db.get(EnrichmentJob, job["id"])
    db.add_all(
        [
            ImportItem(
                job_id=row.id,
                account_id=row.account_id,
                payload_json={
                    "supplier_ref": "REF-1",
                    "variants": [
                        # 2 x 10.50 gros / 2 x 25 conseillé
                        {
                            "quantity": 2,
                            "wholesale_price": "10.50",
                            "retail_price": "25",
                        },
                        # quantité absente -> 1 unité ; pas de prix conseillé
                        {
                            "quantity": None,
                            "wholesale_price": "4.25",
                            "retail_price": None,
                        },
                    ],
                },
            ),
            ImportItem(
                job_id=row.id,
                account_id=row.account_id,
                payload_json={
                    "supplier_ref": "REF-2",
                    "variants": [
                        {"quantity": 3, "wholesale_price": None, "retail_price": None}
                    ],
                },
            ),
        ]
    )
    db.commit()

    totals = import_client.get(f"/imports/{job['id']}").json()["totals"]
    assert totals["quantity"] == 6
    assert Decimal(totals["wholesale_amount"]) == Decimal("25.25")
    assert Decimal(totals["retail_amount"]) == Decimal("50")


def test_download_import_file_streams_original_bytes(
    import_client: TestClient,
) -> None:
    job = _upload(import_client, name="Commande L'Espion.pdf", data=b"%PDF-1.4 espion")

    response = import_client.get(f"/imports/{job['id']}/file")
    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 espion"
    assert response.headers["content-type"].startswith("application/pdf")
    # Inline: the browser previews instead of forcing a download.
    assert response.headers["content-disposition"].startswith("inline")

    csv_job = _upload(import_client, name="commande.csv", data=b"ref;ean\nR1;123\n")
    csv_response = import_client.get(f"/imports/{csv_job['id']}/file")
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert csv_response.content == b"ref;ean\nR1;123\n"

    assert import_client.get("/imports/99999/file").status_code == 404


def test_download_import_file_404_when_file_gone_from_disk(
    import_client: TestClient, upload_dir: Path
) -> None:
    job = _upload(import_client)
    next(upload_dir.iterdir()).unlink()

    response = import_client.get(f"/imports/{job['id']}/file")
    assert response.status_code == 404
    assert response.json()["code"] == "file_not_found"
    assert import_client.get(f"/imports/{job['id']}/file/preview").status_code == 404


def test_preview_tabular_file_returns_first_rows(import_client: TestClient) -> None:
    data = "ref;ean\n" + "".join(f"R{i};36078{i}\n" for i in range(150))
    job = _upload(import_client, name="commande.csv", data=data.encode())

    response = import_client.get(f"/imports/{job['id']}/file/preview")
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "tabular"
    assert body["file_name"] == "commande.csv"
    sheet = body["sheets"][0]
    assert sheet["rows"][0] == ["ref", "ean"]
    assert sheet["rows"][1] == ["R0", "360780"]
    assert len(sheet["rows"]) == 100  # capped
    assert sheet["total_rows"] == 151
    assert sheet["truncated"] is True


def test_preview_pdf_file_returns_pdf_kind_without_rows(
    import_client: TestClient,
) -> None:
    job = _upload(import_client, name="commande.pdf", data=b"%PDF-1.4 fake")

    body = import_client.get(f"/imports/{job['id']}/file/preview").json()
    assert body == {"kind": "pdf", "file_name": "commande.pdf", "sheets": []}


def test_imports_are_isolated_by_account(import_client: TestClient) -> None:
    # A job owned by ANOTHER account must be invisible here.
    db = _db()
    other = Account(name="other-shop")
    db.add(other)
    db.flush()
    foreign = EnrichmentJob(
        account_id=other.id,
        job_type="import",
        selection_json={"file_name": "x.pdf", "file_path": "/nope/x.pdf"},
        config_json={},
    )
    db.add(foreign)
    db.commit()
    foreign_id = foreign.id

    mine = _upload(import_client)

    listing = import_client.get("/imports").json()
    assert [job["id"] for job in listing["items"]] == [mine["id"]]
    assert import_client.get(f"/imports/{foreign_id}").status_code == 404
    assert import_client.get(f"/imports/{foreign_id}/items").status_code == 404
    assert import_client.get(f"/imports/{foreign_id}/file").status_code == 404
    assert import_client.get(f"/imports/{foreign_id}/file/preview").status_code == 404


def test_jobs_list_excludes_import_jobs(import_client: TestClient) -> None:
    imported = _upload(import_client)
    created = import_client.post(
        "/jobs", json={"selection": {"ids": [1]}, "config": {}}
    )
    assert created.status_code == 201
    enrichment_id = created.json()["id"]

    jobs = import_client.get("/jobs").json()
    assert [job["id"] for job in jobs["items"]] == [enrichment_id]

    imports = import_client.get("/imports").json()
    assert [job["id"] for job in imports["items"]] == [imported["id"]]
