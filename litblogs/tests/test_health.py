def test_app_import_does_not_initialize_database(database_existed_after_import):
    assert database_existed_after_import is False


def test_health_endpoint_returns_success(client):
    response = client.get("/api/")

    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to LitBlogs Backend"}


def test_protected_endpoint_requires_authentication(client):
    response = client.get("/api/user/profile")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_protected_endpoint_rejects_malformed_bearer_token(client):
    response = client.get(
        "/api/user/profile",
        headers={"Authorization": "Bearer definitely-not-a-jwt"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
