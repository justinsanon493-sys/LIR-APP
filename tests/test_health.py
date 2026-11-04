"""Smoke test for the health endpoint."""


def test_healthz(app_client):
    response = app_client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json()["ok"] is True
