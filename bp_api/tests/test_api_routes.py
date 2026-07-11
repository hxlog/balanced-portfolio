"""API 路由注册 smoke tests。"""

from bp_api.main import app


def _route_methods(path: str) -> set[str]:
    methods: set[str] = set()
    for route in app.routes:
        if getattr(route, "path", None) == path and hasattr(route, "methods"):
            methods |= set(route.methods or [])
    return methods


def test_put_portfolio_route_registered():
    methods = _route_methods("/api/portfolios/{portfolio_id}")
    assert "PUT" in methods
    assert "GET" in methods
    assert "DELETE" in methods


def test_demo_route_registered():
    assert "GET" in _route_methods("/api/portfolios/demo")
    assert "PATCH" in _route_methods("/api/portfolios/{portfolio_id}/demo")


def test_admin_user_routes_registered():
    assert "GET" in _route_methods("/api/admin/users")
    assert "POST" in _route_methods("/api/admin/users")
    assert "DELETE" in _route_methods("/api/admin/users/{email}")
