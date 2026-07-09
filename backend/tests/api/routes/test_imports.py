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


# -- review edits (PATCH item) -----------------------------------------------


def _add_item(
    job_id: int, payload: dict[str, Any], status: str = "ready_for_review"
) -> int:
    db = _db()
    row = db.get(EnrichmentJob, job_id)
    item = ImportItem(
        job_id=row.id, account_id=row.account_id, status=status, payload_json=payload
    )
    db.add(item)
    db.commit()
    item_id: int = item.id
    return item_id


def test_patch_item_edits_payload(import_client: TestClient) -> None:
    job = _upload(import_client)
    item_id = _add_item(job["id"], {"supplier_ref": "REF-1", "title": "Pull"})

    response = import_client.patch(
        f"/imports/{job['id']}/items/{item_id}",
        json={
            "payload": {
                "supplier_ref": "REF-1",
                "title": "Pull marin",
                "variants": [{"color": "Marine", "size": "M", "quantity": 2}],
            }
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ready_for_review"
    assert body["payload"]["title"] == "Pull marin"
    # Stored normalized through ImportedProduct (defaults filled in).
    assert body["payload"]["variants"][0]["quantity"] == 2
    assert body["payload"]["brand"] is None

    db = _db()
    assert db.get(ImportItem, item_id).payload_json["title"] == "Pull marin"


def test_patch_item_rejects_invalid_payload(import_client: TestClient) -> None:
    job = _upload(import_client)
    item_id = _add_item(job["id"], {"supplier_ref": "REF-1"})

    # supplier_ref is required by the frozen contract.
    response = import_client.patch(
        f"/imports/{job['id']}/items/{item_id}", json={"payload": {"title": "Pull"}}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_payload"
    # The stored payload is untouched.
    db = _db()
    assert db.get(ImportItem, item_id).payload_json == {"supplier_ref": "REF-1"}


def test_patch_item_reject_and_restore(import_client: TestClient) -> None:
    job = _upload(import_client)
    item_id = _add_item(job["id"], {"supplier_ref": "REF-1"})

    rejected = import_client.patch(
        f"/imports/{job['id']}/items/{item_id}", json={"status": "rejected"}
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    restored = import_client.patch(
        f"/imports/{job['id']}/items/{item_id}", json={"status": "ready_for_review"}
    )
    assert restored.json()["status"] == "ready_for_review"

    # Other statuses are not review-editable.
    for status in ("approved", "applied", "failed", "bogus"):
        response = import_client.patch(
            f"/imports/{job['id']}/items/{item_id}", json={"status": status}
        )
        assert response.status_code == 400, status
        assert response.json()["code"] == "invalid_status"


def test_patch_item_cross_404s(import_client: TestClient) -> None:
    job_a = _upload(import_client)
    job_b = _upload(import_client)
    item_id = _add_item(job_a["id"], {"supplier_ref": "REF-1"})

    # Item exists but belongs to another job.
    assert (
        import_client.patch(
            f"/imports/{job_b['id']}/items/{item_id}", json={"status": "rejected"}
        ).status_code
        == 404
    )
    # Unknown item / unknown job.
    assert (
        import_client.patch(
            f"/imports/{job_a['id']}/items/99999", json={"status": "rejected"}
        ).status_code
        == 404
    )
    assert (
        import_client.patch(
            f"/imports/99999/items/{item_id}", json={"status": "rejected"}
        ).status_code
        == 404
    )


# -- profile selection (PUT /profile) ------------------------------------------


def _create_profile(client: TestClient, **overrides: Any) -> int:
    payload: dict[str, Any] = {"name": "Profil", **overrides}
    response = client.post("/import-profiles", json=payload)
    assert response.status_code == 201, response.text
    profile_id: int = response.json()["id"]
    return profile_id


def test_put_profile_selects_and_clears(import_client: TestClient) -> None:
    job = _upload(import_client)
    assert job["profile_id"] is None
    profile_id = _create_profile(import_client)

    selected = import_client.put(
        f"/imports/{job['id']}/profile", json={"profile_id": profile_id}
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["profile_id"] == profile_id
    assert import_client.get(f"/imports/{job['id']}").json()["profile_id"] == profile_id

    cleared = import_client.put(
        f"/imports/{job['id']}/profile", json={"profile_id": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["profile_id"] is None


def test_put_profile_404_on_foreign_or_unknown_profile(
    import_client: TestClient,
) -> None:
    job = _upload(import_client)

    assert (
        import_client.put(
            f"/imports/{job['id']}/profile", json={"profile_id": 99999}
        ).status_code
        == 404
    )

    db = _db()
    other = Account(name="other-shop")
    db.add(other)
    db.flush()
    from app.models import ImportProfile

    foreign = ImportProfile(account_id=other.id, name="Foreign", config_json={})
    db.add(foreign)
    db.commit()
    assert (
        import_client.put(
            f"/imports/{job['id']}/profile", json={"profile_id": foreign.id}
        ).status_code
        == 404
    )


# -- CSV rendering (GET /rows, GET /csv) ---------------------------------------


def _coefficient_profile(client: TestClient) -> int:
    return _create_profile(
        client,
        name="L'Espion",
        config={
            "price_mode": "coefficient",
            "coefficient": "2.8",
            "round_up_to": "5",
            "barcode_mode": "constructed",
        },
    )


def _staged_job(client: TestClient) -> dict[str, Any]:
    """An extracted job: document facts + one kept item + one rejected item."""
    job = _upload(client)
    db = _db()
    row = db.get(EnrichmentJob, job["id"])
    row.status = "completed"
    row.config_json = {
        "document": {"po_number": "PO-889", "supplier": "L'Espion"},
    }
    db.commit()
    _add_item(
        job["id"],
        {
            "supplier_ref": "REF-1",
            "title": "Pull marin",
            "variants": [
                {
                    "color": "Marine",
                    "size": "M",
                    "quantity": 2,
                    "wholesale_price": "10.50",
                }
            ],
        },
    )
    _add_item(
        job["id"],
        {"supplier_ref": "REF-REJ", "variants": [{"wholesale_price": "99"}]},
        status="rejected",
    )
    return job


def test_get_rows_applies_coefficient_and_excludes_rejected(
    import_client: TestClient,
) -> None:
    job = _staged_job(import_client)
    profile_id = _coefficient_profile(import_client)

    response = import_client.get(
        f"/imports/{job['id']}/rows", params={"profile_id": profile_id}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["columns"][0] == "id"
    assert body["row_count"] == 1  # the rejected item never renders
    row = dict(zip(body["columns"], body["rows"][0], strict=True))
    # 10.50 x 2.8 = 29.4 -> rounded UP to the nearest 5 -> 30.
    assert row["price"] == "30"
    assert row["wholesale_price"] == "10.5"
    assert row["reference_code"] == "REF-1"
    assert row["variant_barcode"] == "REF-1-Marine-M"
    # Fallback supplier comes from the extracted document.
    assert row["supplier"] == "L'Espion"
    assert row["quantity"] == "2"
    assert body["warnings"] == []


def test_get_rows_uses_selected_profile_and_requires_one(
    import_client: TestClient,
) -> None:
    job = _staged_job(import_client)

    # No explicit ?profile_id and none selected -> 400 profile_required.
    missing = import_client.get(f"/imports/{job['id']}/rows")
    assert missing.status_code == 400
    assert missing.json()["code"] == "profile_required"

    profile_id = _coefficient_profile(import_client)
    import_client.put(f"/imports/{job['id']}/profile", json={"profile_id": profile_id})
    selected = import_client.get(f"/imports/{job['id']}/rows")
    assert selected.status_code == 200
    assert selected.json()["row_count"] == 1


def test_get_rows_invalid_profile_config_is_400(import_client: TestClient) -> None:
    job = _staged_job(import_client)
    # coefficient mode without a coefficient -> render_rows raises ValueError.
    profile_id = _create_profile(
        import_client, config={"price_mode": "coefficient", "coefficient": None}
    )

    response = import_client.get(
        f"/imports/{job['id']}/rows", params={"profile_id": profile_id}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_profile"


def test_get_csv_downloads_named_attachment(import_client: TestClient) -> None:
    job = _staged_job(import_client)
    profile_id = _coefficient_profile(import_client)

    response = import_client.get(
        f"/imports/{job['id']}/csv", params={"profile_id": profile_id}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="import_l-espion_po-889.csv"'
    )
    lines = response.text.strip().split("\n")
    assert lines[0].startswith("id,title,")
    assert len(lines) == 2  # header + the single kept variant
    assert ",REF-1-Marine-M," in lines[1]
    assert ",30," in lines[1]


def test_get_csv_file_name_falls_back_to_job_id(import_client: TestClient) -> None:
    job = _upload(import_client)
    _add_item(job["id"], {"supplier_ref": "R1", "variants": [{"retail_price": "25"}]})
    profile_id = _create_profile(import_client)

    response = import_client.get(
        f"/imports/{job['id']}/csv", params={"profile_id": profile_id}
    )
    assert response.status_code == 200
    assert (
        response.headers["content-disposition"]
        == f'attachment; filename="import_{job["id"]}.csv"'
    )


# -- transfer (POST /transfer) --------------------------------------------------


class _FakeXano:
    """Records product_import calls (never touches the network)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def product_import(
        self, *, file_name: str, csv_bytes: bytes, location_id: int
    ) -> Any:
        self.calls.append(
            {
                "file_name": file_name,
                "csv_bytes": csv_bytes,
                "location_id": location_id,
            }
        )
        return {"ok": True}


@pytest.fixture
def fake_xano() -> Generator[_FakeXano]:
    from app.api.deps import get_xano_client

    fake = _FakeXano()
    app.dependency_overrides[get_xano_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_xano_client, None)


def test_transfer_pushes_csv_and_applies_items(
    import_client: TestClient, fake_xano: _FakeXano
) -> None:
    job = _staged_job(import_client)
    profile_id = _coefficient_profile(import_client)
    import_client.put(f"/imports/{job['id']}/profile", json={"profile_id": profile_id})

    response = import_client.post(
        f"/imports/{job['id']}/transfer", json={"location_id": 7}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "row_count": 1}

    # The Xano client received the rendered CSV under the computed name.
    assert len(fake_xano.calls) == 1
    call = fake_xano.calls[0]
    assert call["file_name"] == "import_l-espion_po-889.csv"
    assert call["location_id"] == 7
    csv_text = call["csv_bytes"].decode("utf-8")
    assert csv_text.startswith("id,title,")
    assert ",REF-1-Marine-M," in csv_text

    # Kept items become applied; rejected ones stay rejected.
    db = _db()
    statuses = {
        item.payload_json["supplier_ref"]: item.status
        for item in db.query(ImportItem).filter(ImportItem.job_id == job["id"])
    }
    assert statuses == {"REF-1": "applied", "REF-REJ": "rejected"}

    # The transfer facts are recorded on the job.
    transfer = db.get(EnrichmentJob, job["id"]).config_json["transfer"]
    assert transfer["location_id"] == 7
    assert transfer["row_count"] == 1
    assert transfer["transferred_at"]  # ISO timestamp


def test_transfer_accepts_explicit_profile_id(
    import_client: TestClient, fake_xano: _FakeXano
) -> None:
    job = _staged_job(import_client)
    profile_id = _coefficient_profile(import_client)

    response = import_client.post(
        f"/imports/{job['id']}/transfer",
        json={"location_id": 3, "profile_id": profile_id},
    )
    assert response.status_code == 200
    assert fake_xano.calls[0]["location_id"] == 3


def test_transfer_nothing_to_transfer(
    import_client: TestClient, fake_xano: _FakeXano
) -> None:
    job = _upload(import_client)
    _add_item(job["id"], {"supplier_ref": "R1", "variants": [{}]}, status="rejected")
    profile_id = _create_profile(import_client)

    response = import_client.post(
        f"/imports/{job['id']}/transfer",
        json={"location_id": 7, "profile_id": profile_id},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "nothing_to_transfer"
    assert fake_xano.calls == []
    # Nothing was marked applied and no transfer was recorded.
    db = _db()
    assert db.get(EnrichmentJob, job["id"]).config_json.get("transfer") is None


def test_transfer_requires_profile(
    import_client: TestClient, fake_xano: _FakeXano
) -> None:
    job = _staged_job(import_client)

    response = import_client.post(
        f"/imports/{job['id']}/transfer", json={"location_id": 7}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "profile_required"
    assert fake_xano.calls == []


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
