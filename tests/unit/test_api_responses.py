from flask import g

from app.api.v1.responses import collection_response, error_response, item_response


def test_item_envelope(app):
    with app.test_request_context("/"):
        g.request_id = "req_test"
        response, status = item_response({"status": "ok"})
        assert status == 200
        assert response.get_json() == {
            "ok": True,
            "api_version": "v1",
            "item": {"status": "ok"},
        }


def test_collection_envelope_paginates(app):
    with app.test_request_context("/"):
        response, status = collection_response([{"id": "one"}], total=2, limit=1, offset=0)
        assert status == 200
        assert response.get_json()["next_offset"] == 1
        assert response.get_json()["has_more"] is True


def test_error_envelope_uses_request_id(app):
    with app.test_request_context("/"):
        g.request_id = "req_test"
        response, status = error_response("not_found", "Missing.", 404)
        assert status == 404
        assert response.get_json()["error"]["request_id"] == "req_test"
