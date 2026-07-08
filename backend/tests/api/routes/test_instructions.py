"""Tests for the instruction library CRUD and its snapshot into job configs."""

from typing import Any

from fastapi.testclient import TestClient


def _create(
    client: TestClient,
    name: str,
    content: str,
    categories: list[str] | None = None,
) -> dict[str, Any]:
    response = client.post(
        "/instructions",
        json={"name": name, "content": content, "categories": categories or []},
    )
    assert response.status_code == 201
    body: dict[str, Any] = response.json()
    return body


def test_instructions_require_authentication(client: TestClient) -> None:
    assert client.get("/instructions").status_code == 401
    assert (
        client.post("/instructions", json={"name": "x", "content": "y"}).status_code
        == 401
    )


def test_instructions_crud_roundtrip(auth_client: TestClient) -> None:
    created = _create(auth_client, "Ton sobre", "Vouvoiement, phrases courtes.")
    assert created["name"] == "Ton sobre"
    assert created["content"] == "Vouvoiement, phrases courtes."
    assert created["categories"] == []
    assert created["created_at"]

    _create(auth_client, "Accessoires", "Mets en avant la matière.", ["Sacs"])

    # Listing is sorted by name.
    listing = auth_client.get("/instructions")
    assert listing.status_code == 200
    assert [row["name"] for row in listing.json()] == ["Accessoires", "Ton sobre"]

    # Update.
    updated = auth_client.put(
        f"/instructions/{created['id']}",
        json={
            "name": "Ton chaleureux",
            "content": "Tutoiement.",
            "categories": ["Polos"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Ton chaleureux"
    assert updated.json()["categories"] == ["Polos"]

    # Validation: empty name/content are rejected.
    assert (
        auth_client.post("/instructions", json={"name": "", "content": "x"}).status_code
        == 422
    )
    assert (
        auth_client.post("/instructions", json={"name": "x", "content": ""}).status_code
        == 422
    )

    # Delete.
    assert auth_client.delete(f"/instructions/{created['id']}").status_code == 204
    assert [row["name"] for row in auth_client.get("/instructions").json()] == [
        "Accessoires"
    ]

    # Unknown ids -> 404 with the standard error code.
    missing = auth_client.put("/instructions/99999", json={"name": "x", "content": "y"})
    assert missing.status_code == 404
    assert auth_client.delete("/instructions/99999").status_code == 404


def test_instructions_are_account_scoped(auth_client: TestClient) -> None:
    created = _create(auth_client, "Ton sobre", "Vouvoiement.")

    # Move the signed-in user to a different account: the library is empty
    # there, and the other account's instruction is unreachable (404).
    from app.api.deps import get_db
    from app.main import app
    from app.models import Account, User

    db = next(app.dependency_overrides[get_db]())
    other = Account(name="other-shop")
    db.add(other)
    db.flush()
    user = db.query(User).filter_by(email="dev@catalogai.io").one()
    user.account_id = other.id
    db.commit()

    assert auth_client.get("/instructions").json() == []
    assert (
        auth_client.put(
            f"/instructions/{created['id']}", json={"name": "x", "content": "y"}
        ).status_code
        == 404
    )
    assert auth_client.delete(f"/instructions/{created['id']}").status_code == 404


def test_create_job_snapshots_instruction_id(auth_client: TestClient) -> None:
    instruction = _create(auth_client, "Ton sobre", "Vouvoiement, phrases courtes.")

    job = auth_client.post(
        "/jobs",
        json={
            "selection": {"ids": [1]},
            "config": {"instruction_id": instruction["id"]},
        },
    )
    assert job.status_code == 201
    config = job.json()["config_json"]
    # Snapshot: content copied, the reference dropped.
    assert config["editorial_instructions"] == "Vouvoiement, phrases courtes."
    assert "instruction_id" not in config
    # And no per-category snapshot when instructions are pinned.
    assert "category_instructions" not in config

    # Deleting the instruction later leaves the job untouched.
    assert auth_client.delete(f"/instructions/{instruction['id']}").status_code == 204
    persisted = auth_client.get(f"/jobs/{job.json()['id']}").json()
    assert (
        persisted["config_json"]["editorial_instructions"]
        == "Vouvoiement, phrases courtes."
    )


def test_create_job_unknown_instruction_id_is_404(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/jobs", json={"selection": {"ids": [1]}, "config": {"instruction_id": 4242}}
    )
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_explicit_instructions_beat_instruction_id(auth_client: TestClient) -> None:
    instruction = _create(auth_client, "Ton sobre", "Vouvoiement.")

    job = auth_client.post(
        "/jobs",
        json={
            "selection": {"ids": [1]},
            "config": {
                "instruction_id": instruction["id"],
                "editorial_instructions": "Consignes du job.",
            },
        },
    ).json()
    assert job["config_json"]["editorial_instructions"] == "Consignes du job."
    assert "instruction_id" not in job["config_json"]


def test_create_job_snapshots_category_defaults(auth_client: TestClient) -> None:
    _create(auth_client, "Polos", "Parle du col.", ["Polos"])
    _create(auth_client, "Bas", "Parle de la coupe.", ["Shorts", "Pantalons"])
    # Most recent claim on a category wins.
    _create(auth_client, "Polos v2", "Parle du coton piqué.", ["Polos"])

    job = auth_client.post("/jobs", json={"selection": {"ids": [1]}}).json()
    assert job["config_json"]["category_instructions"] == {
        "Polos": "Parle du coton piqué.",
        "Shorts": "Parle de la coupe.",
        "Pantalons": "Parle de la coupe.",
    }
    assert "editorial_instructions" not in job["config_json"]

    # Pinned instructions (explicit or via instruction_id) skip the snapshot.
    pinned = auth_client.post(
        "/jobs",
        json={
            "selection": {"ids": [2]},
            "config": {"editorial_instructions": "Consignes du job."},
        },
    ).json()
    assert "category_instructions" not in pinned["config_json"]


def test_account_default_instructions_outrank_category_snapshot(
    auth_client: TestClient,
) -> None:
    """Precedence: account editorial_instructions > category_instructions —
    both are stored, but the pipeline prefers editorial_instructions."""
    _create(auth_client, "Polos", "Parle du col.", ["Polos"])
    assert (
        auth_client.put(
            "/settings/account",
            json={"editorial_instructions": "Défaut boutique."},
        ).status_code
        == 200
    )

    job = auth_client.post("/jobs", json={"selection": {"ids": [1]}}).json()
    assert job["config_json"]["editorial_instructions"] == "Défaut boutique."
    assert job["config_json"]["category_instructions"] == {"Polos": "Parle du col."}
