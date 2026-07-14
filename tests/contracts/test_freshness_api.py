from app.shared.operations import OperationService


def test_freshness_collection_uses_contract(authenticated_client):
    response = authenticated_client.get("/api/v1/freshness")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["count"] == 6
    assert payload["items"][0]["state"] == "missing"


def test_operation_detail_contract(authenticated_client, app):
    with app.app_context():
        operation = OperationService.start(kind="refresh", domain="books")
        operation_id = operation.id
    response = authenticated_client.get(f"/api/v1/operations/{operation_id}")

    assert response.status_code == 200
    assert response.get_json()["item"]["domain"] == "books"
    assert authenticated_client.get("/api/v1/operations/missing").status_code == 404
