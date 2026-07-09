"""Tests for the import profile CRUD routes (/import-profiles)."""

from typing import Any

from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.main import app
from app.models import Account, ImportProfile


def _db() -> Any:
    return next(app.dependency_overrides[get_db]())


def _create(client: TestClient, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": "L'Espion", **overrides}
    response = client.post("/import-profiles", json=payload)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_import_profiles_require_authentication(client: TestClient) -> None:
    assert client.get("/import-profiles").status_code == 401
    assert client.post("/import-profiles", json={"name": "x"}).status_code == 401


def test_create_profile_defaults_and_lowercased_supplier_match(
    auth_client: TestClient,
) -> None:
    profile = _create(auth_client, supplier_match="  L'Espion  ")

    assert profile["name"] == "L'Espion"
    # Stored stripped + lowercased for supplier auto-matching.
    assert profile["supplier_match"] == "l'espion"
    # Every config field has a safe default.
    config = profile["config"]
    assert config["price_mode"] == "retail_as_is"
    assert config["barcode_mode"] == "ean"
    assert config["brand_mode"] == "as_extracted"
    assert config["tax_rate"] == "20"
    assert config["status"] == "active"


def test_create_profile_with_coefficient_config(auth_client: TestClient) -> None:
    profile = _create(
        auth_client,
        config={"price_mode": "coefficient", "coefficient": "2.8", "round_up_to": "5"},
    )
    assert profile["config"]["price_mode"] == "coefficient"
    assert profile["config"]["coefficient"] == "2.8"

    # Round-trips through storage (Decimal stored as JSON string).
    listing = auth_client.get("/import-profiles").json()
    assert listing[0]["config"]["coefficient"] == "2.8"


def test_create_profile_validates_name(auth_client: TestClient) -> None:
    assert auth_client.post("/import-profiles", json={}).status_code == 422
    assert auth_client.post("/import-profiles", json={"name": ""}).status_code == 422


def test_list_profiles_sorted_by_name(auth_client: TestClient) -> None:
    _create(auth_client, name="Zeta")
    _create(auth_client, name="Alpha")

    listing = auth_client.get("/import-profiles")
    assert listing.status_code == 200
    assert [p["name"] for p in listing.json()] == ["Alpha", "Zeta"]


def test_update_profile_partial_fields(auth_client: TestClient) -> None:
    profile = _create(auth_client, supplier_match="garcia")

    renamed = auth_client.patch(
        f"/import-profiles/{profile['id']}", json={"name": "Bambinoh — Garcia"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Bambinoh — Garcia"
    # Untouched fields are preserved.
    assert renamed.json()["supplier_match"] == "garcia"
    assert renamed.json()["config"] == profile["config"]

    reconfigured = auth_client.patch(
        f"/import-profiles/{profile['id']}",
        json={
            "supplier_match": "  GARCIA JEANS ",
            "config": {"price_mode": "coefficient", "coefficient": "2"},
        },
    )
    assert reconfigured.status_code == 200
    assert reconfigured.json()["supplier_match"] == "garcia jeans"
    assert reconfigured.json()["config"]["coefficient"] == "2"
    assert reconfigured.json()["name"] == "Bambinoh — Garcia"


def test_delete_profile(auth_client: TestClient) -> None:
    profile = _create(auth_client)

    response = auth_client.delete(f"/import-profiles/{profile['id']}")
    assert response.status_code == 204

    assert auth_client.get("/import-profiles").json() == []
    assert (
        auth_client.delete(f"/import-profiles/{profile['id']}").status_code == 404
    )  # already gone


def _foreign_profile() -> int:
    """Seed a profile owned by ANOTHER account, return its id."""
    db = _db()
    other = Account(name="other-shop")
    db.add(other)
    db.flush()
    foreign = ImportProfile(
        account_id=other.id, name="Foreign", supplier_match="", config_json={}
    )
    db.add(foreign)
    db.commit()
    profile_id: int = foreign.id
    return profile_id


def test_profiles_are_isolated_by_account(auth_client: TestClient) -> None:
    mine = _create(auth_client)
    foreign_id = _foreign_profile()

    listing = auth_client.get("/import-profiles").json()
    assert [p["id"] for p in listing] == [mine["id"]]

    assert (
        auth_client.patch(
            f"/import-profiles/{foreign_id}", json={"name": "hack"}
        ).status_code
        == 404
    )
    assert auth_client.delete(f"/import-profiles/{foreign_id}").status_code == 404
    # The foreign profile is untouched.
    db = _db()
    assert db.get(ImportProfile, foreign_id).name == "Foreign"
