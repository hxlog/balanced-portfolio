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


def test_portfolio_meta_route_accepts_full_payload():
    """Task 5: PATCH /meta 扩展为免重算全字段保存, 请求模型须为 UpdatePortfolioIn。"""
    import inspect

    from bp_api.main import update_portfolio_meta

    sig = inspect.signature(update_portfolio_meta)
    assert "payload" in sig.parameters
    ann = sig.parameters["payload"].annotation
    ann_name = getattr(ann, "__name__", None) or str(ann)
    assert "UpdatePortfolioIn" in ann_name


def test_recompute_all_route_registered():
    """Task 7: POST /api/admin/portfolios/recompute-all, 必须挂超管依赖。"""
    import inspect

    from bp_api import auth, main

    assert "POST" in _route_methods("/api/admin/portfolios/recompute-all")
    sig = inspect.signature(main.recompute_all_portfolios)
    dep = sig.parameters["user"].default
    assert getattr(dep, "dependency", None) is auth.require_super_admin
