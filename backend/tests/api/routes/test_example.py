from fastapi.testclient import TestClient


def test_example_returns_payload(client: TestClient) -> None:
    response = client.get("/example")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": "Example endpoint reached",
        "sample_id": 1,
    }


def test_example_accepts_sample_id(client: TestClient) -> None:
    response = client.get("/example?sample_id=7")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": "Example endpoint reached",
        "sample_id": 7,
    }
