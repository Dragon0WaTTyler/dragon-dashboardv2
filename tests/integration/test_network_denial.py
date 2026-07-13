import socket


def test_base_get_routes_make_no_network_calls(client, admin_user, monkeypatch):
    def deny_network(*args, **kwargs):
        raise AssertionError("GET route attempted an external network call")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/auth/login").status_code == 200


def test_protected_get_routes_make_no_network_calls(authenticated_client, monkeypatch):
    def deny_network(*args, **kwargs):
        raise AssertionError("Protected GET attempted an external network call")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    assert authenticated_client.get("/").status_code == 200
    assert authenticated_client.get("/admin/design-system").status_code == 200
