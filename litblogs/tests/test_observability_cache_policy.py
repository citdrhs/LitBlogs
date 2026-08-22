from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from observability import RequestObservabilityMiddleware


def _response_with_cache_control(value: str):
    async def endpoint(_request):
        return PlainTextResponse("ok", headers={"Cache-Control": value})

    app = Starlette(routes=[Route("/api/private", endpoint)])
    app.add_middleware(RequestObservabilityMiddleware)
    return TestClient(app).get("/api/private")


def test_api_middleware_preserves_the_reviewed_private_no_store_policy():
    response = _response_with_cache_control("private, no-store")

    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["pragma"] == "no-cache"


def test_api_middleware_replaces_every_other_cache_policy_with_no_store():
    for policy in ("public, max-age=3600", "public, no-store", "no-cache", ""):
        response = _response_with_cache_control(policy)
        assert response.headers["cache-control"] == "no-store"
