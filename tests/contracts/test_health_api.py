def test_health_contract(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert response.get_json() == {
        "ok": True,
        "api_version": "v1",
        "item": {"status": "ok", "database": "available"},
    }
    assert response.headers["X-Request-ID"].startswith("req_")


def test_unknown_api_route_has_safe_contract(client):
    response = client.get("/api/v1/does-not-exist")
    payload = response.get_json()
    assert response.status_code == 404
    assert payload["ok"] is False
    assert payload["api_version"] == "v1"
    assert payload["error"]["code"] == "not_found"
    assert payload["error"]["request_id"].startswith("req_")
    serialized = response.get_data(as_text=True).lower()
    assert "c:\\users" not in serialized
    assert "traceback" not in serialized
