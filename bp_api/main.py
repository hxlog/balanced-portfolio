"""Balanced Portfolio - FastAPI 应用。

启动: uvicorn bp_api.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import random
import time
from contextlib import asynccontextmanager
from datetime import date, timedelta

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from . import auth, cache, db, repositories as repo, tasking, tasks
from .schemas import (
    AssetAdminIn,
    AssetSelectableIn,
    ChangePasswordIn,
    CopyPortfolioIn,
    CreatePortfolioIn,
    CreateUserIn,
    DisableTotpIn,
    LoginIn,
    PortfolioMetaIn,
    ReorderPortfoliosIn,
    SetDemoIn,
    SetupTotpIn,
    UpdateUserIn,
    UpdatePortfolioIn,
    VerifyTotpIn,
)
from .settings import load_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("bp_api")

settings = load_settings()


def _validate_portfolio_payload(payload: CreatePortfolioIn | UpdatePortfolioIn) -> None:
    if not payload.assets:
        raise HTTPException(400, "至少选择一个资产")
    quadrants = {a.quadrant for a in payload.assets}
    if not quadrants:
        raise HTTPException(400, "资产需指定象限")
    seen: set[tuple[str, str, str]] = set()
    for a in payload.assets:
        key = (a.symbol, a.source, a.quadrant)
        if key in seen:
            raise HTTPException(400, f"重复配置: {a.symbol}@{a.source} 在象限 {a.quadrant}")
        seen.add(key)
    n_unique = repo.count_unique_assets(payload.assets)
    if n_unique * payload.max_weight < 0.999:
        raise HTTPException(
            400,
            f"单资产最大权重 {payload.max_weight:.2%} 与 {n_unique} 个独立品种不兼容"
            f"(需满足 品种数×上限≥100%)",
        )


def _enqueue_backtest(
    conn,
    portfolio_id: int,
    owner_user_id: int | None,
    task_type: str = "backtest",
) -> str:
    active = tasking.find_active_portfolio_task(conn, portfolio_id)
    if active:
        return active
    task_id = tasking.create_task(
        conn,
        task_type,
        portfolio_id=portfolio_id,
        owner_user_id=owner_user_id,
        progress_total=6,
        message="回测已排队",
    )
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE bp_portfolio SET status='running', error=NULL WHERE portfolio_id=%s",
            (portfolio_id,),
        )
    return task_id


def _dispatch_backtest(task_id: str, portfolio_id: int, background_tasks: BackgroundTasks) -> None:
    """事务提交后再派发任务，避免 worker 看不到未提交的 bp_task。"""
    celery_id = tasking.enqueue_backtest(task_id, portfolio_id)
    if celery_id:
        with db.get_conn() as conn:
            tasking.set_celery_id(conn, task_id, celery_id)
            conn.commit()
    else:
        background_tasks.add_task(tasks.run_backtest_background, portfolio_id, settings, task_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_pool(settings)
    logger.info("DB 连接池已初始化: %s", settings.db.safe_repr())
    try:
        from bp_ingest.http_session import install_hardened_session
        install_hardened_session()
    except Exception as exc:  # noqa: BLE001
        logger.warning("requests 会话硬化失败(忽略): %s", exc)
    try:
        auth.ensure_admin()
        logger.info("管理员账号已就绪: %s", settings.admin_email)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_admin 失败(稍后可重试): %s", exc)
    yield
    db.close_pool()


from . import cffex as _cffex
from . import otc_api as _otc

app = FastAPI(title="Balanced Portfolio API", version="0.1.0", lifespan=lifespan)
_cffex.register_routes(app)
_otc.register_routes(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------
# 鉴权
# ---------------------------------------------------------------------
@app.post("/api/auth/login")
def login(payload: LoginIn, request: Request) -> dict:
    email = payload.email.strip().lower()
    ip = request.client.host if request.client else ""
    return auth.authenticate_login(email, payload.password, ip, payload.otp_code)


@app.get("/api/auth/me")
def me(user: auth.UserContext = Depends(auth.require_user)) -> dict:
    return auth.auth_profile(user)


@app.post("/api/auth/refresh")
def refresh_session(request: Request) -> dict:
    """滑动续期: 有效或 grace 窗口内的 token 可换取新 JWT。"""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(401, "需要登录")
    token = auth_header.split(" ", 1)[1].strip()
    email = auth.decode_token_with_grace(token)
    if not email:
        raise HTTPException(401, "登录已失效或无权限")
    user = auth.get_user_by_email(email)
    if not user:
        raise HTTPException(401, "登录已失效或无权限")
    return {"token": auth.refresh_token(email), "email": email}


@app.post("/api/auth/2fa/setup")
def setup_2fa(payload: SetupTotpIn, user: auth.UserContext = Depends(auth.require_user)) -> dict:
    return auth.setup_totp(user.email, payload.current_code)


@app.post("/api/auth/2fa/verify")
def verify_2fa(payload: VerifyTotpIn, user: auth.UserContext = Depends(auth.require_user)) -> dict:
    auth.enable_totp(user.email, payload.code)
    return {"ok": True}


@app.post("/api/auth/2fa/disable")
def disable_2fa(payload: DisableTotpIn, user: auth.UserContext = Depends(auth.require_user)) -> dict:
    auth.disable_totp(user.email, payload.code)
    return {"ok": True}


@app.get("/api/admin/users")
def list_admin_users(_: auth.UserContext = Depends(auth.require_super_admin)) -> dict:
    return {"users": auth.list_users()}


@app.post("/api/admin/users")
def create_admin_user(payload: CreateUserIn, _: str = Depends(auth.require_super_admin)) -> dict:
    auth.create_user(payload.email, payload.password)
    return {"ok": True}


@app.delete("/api/admin/users/{email}")
def delete_admin_user(email: str, actor: auth.UserContext = Depends(auth.require_super_admin)) -> dict:
    auth.delete_user(email, actor.email)
    return {"ok": True}


@app.patch("/api/admin/users/{email}")
def update_admin_user(email: str, payload: UpdateUserIn, _: auth.UserContext = Depends(auth.require_super_admin)) -> dict:
    auth.update_user(email, payload.portfolio_limit, payload.status)
    return {"ok": True}


@app.post("/api/auth/change-password")
def change_password(payload: ChangePasswordIn, user: auth.UserContext = Depends(auth.require_admin)) -> dict:
    auth.change_password(user.email, payload.old_password, payload.new_password)
    return {"ok": True}


@app.get("/api/assets")
def get_assets() -> dict:
    with db.get_conn() as conn:
        assets = repo.list_assets(conn)
    return {"assets": assets}


@app.get("/api/portfolios")
def list_portfolios(user: auth.UserContext | None = Depends(auth.optional_user)) -> dict:
    with db.get_conn() as conn:
        return {"portfolios": repo.list_portfolios(conn, user.user_id if user else None, user.is_admin if user else False)}


@app.patch("/api/portfolios/order")
def reorder_portfolios(
    payload: ReorderPortfoliosIn,
    user: auth.UserContext = Depends(auth.require_user),
) -> dict:
    if user.user_id is None:
        raise HTTPException(401, "需要登录")
    with db.get_conn() as conn:
        repo.reorder_portfolios(conn, user.user_id, payload.ordered_ids)
        conn.commit()
    return {"ok": True}


@app.post("/api/portfolios")
def create_portfolio(
    payload: CreatePortfolioIn,
    background_tasks: BackgroundTasks,
    user: auth.UserContext = Depends(auth.require_user),
) -> dict:
    _validate_portfolio_payload(payload)
    with db.get_conn() as conn:
        if not user.is_admin and user.user_id is not None:
            limit = repo.get_user_portfolio_limit(conn, user.user_id)
            if limit is not None and repo.count_user_portfolios(conn, user.user_id) >= limit:
                raise HTTPException(403, f"每个用户最多创建 {limit} 个投资组合")
        pid = repo.create_portfolio(conn, payload, user.user_id)
        task_id = _enqueue_backtest(conn, pid, user.user_id)
        conn.commit()
    _dispatch_backtest(task_id, pid, background_tasks)
    return {"portfolio_id": pid, "status": "running", "task_id": task_id}


@app.put("/api/portfolios/{portfolio_id}")
def update_portfolio(
    portfolio_id: int,
    payload: UpdatePortfolioIn,
    background_tasks: BackgroundTasks,
    user: auth.UserContext = Depends(auth.require_user),
) -> dict:
    _validate_portfolio_payload(payload)
    with db.get_conn() as conn:
        try:
            st = repo.get_portfolio_status(conn, portfolio_id)
        except KeyError:
            raise HTTPException(404, "组合不存在")
        if not repo.can_edit_portfolio(conn, portfolio_id, user.user_id, user.is_admin):
            raise HTTPException(403, "无权编辑该组合")
        if st["status"] == "running":
            raise HTTPException(409, "回测进行中, 请稍后再编辑")
        try:
            repo.update_portfolio(conn, portfolio_id, payload, user.user_id)
            task_id = _enqueue_backtest(conn, portfolio_id, user.user_id)
        except KeyError:
            raise HTTPException(404, "组合不存在")
        conn.commit()
    _dispatch_backtest(task_id, portfolio_id, background_tasks)
    return {"portfolio_id": portfolio_id, "status": "running", "task_id": task_id}


@app.patch("/api/portfolios/{portfolio_id}/meta")
def update_portfolio_meta(
    portfolio_id: int,
    payload: PortfolioMetaIn,
    user: auth.UserContext = Depends(auth.require_user),
) -> dict:
    """仅更新名称/描述, 不触发回测。"""
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "组合名称不能为空")
    with db.get_conn() as conn:
        try:
            repo.get_portfolio_status(conn, portfolio_id)
        except KeyError:
            raise HTTPException(404, "组合不存在")
        if not repo.can_edit_portfolio(conn, portfolio_id, user.user_id, user.is_admin):
            raise HTTPException(403, "无权编辑该组合")
        try:
            repo.update_portfolio_meta(
                conn, portfolio_id, name, payload.description.strip(), user.user_id
            )
        except KeyError:
            raise HTTPException(404, "组合不存在")
        conn.commit()
    cache.delete_pattern(f"portfolio_result:{portfolio_id}:*")
    return {"portfolio_id": portfolio_id}


@app.get("/api/portfolios/demo")
def get_demo(
    portfolio_id: int | None = None,
    method: str | None = None,
    benchmark: str | None = None,
) -> dict:
    with db.get_conn() as conn:
        pid = repo.get_demo_id(conn, portfolio_id)
        if pid is None:
            if portfolio_id is not None:
                raise HTTPException(404, "该组合不是示例组合或不存在")
            raise HTTPException(404, "未配置 demo 组合, 请先执行 04_seed_demo_portfolio.sql")
        info = repo.get_portfolio_dict(conn, pid)
        if info["status"] == "running":
            raise HTTPException(409, "回测进行中, 请稍后再试")
        if info["status"] == "error":
            raise HTTPException(422, info.get("error") or "回测失败")
        if info["status"] != "done":
            raise HTTPException(409, "示例组合尚未完成回测")
        return repo.get_result(conn, pid, method, benchmark)


@app.patch("/api/portfolios/{portfolio_id}/demo")
def set_portfolio_demo(
    portfolio_id: int,
    payload: SetDemoIn,
    user: auth.UserContext = Depends(auth.require_super_admin),
) -> dict:
    with db.get_conn() as conn:
        try:
            repo.set_portfolio_demo(conn, portfolio_id, payload.is_demo)
            conn.commit()
        except KeyError:
            raise HTTPException(404, "组合不存在")
    return {"portfolio_id": portfolio_id, "is_demo": payload.is_demo}


@app.get("/api/portfolios/{portfolio_id}")
def get_portfolio(
    portfolio_id: int,
    user: auth.UserContext | None = Depends(auth.optional_user),
) -> dict:
    with db.get_conn() as conn:
        try:
            if not repo.can_view_portfolio(conn, portfolio_id, user.user_id if user else None, user.is_admin if user else False):
                raise HTTPException(403, "无权查看该组合")
            return repo.get_portfolio_dict(conn, portfolio_id)
        except KeyError:
            raise HTTPException(404, "组合不存在")


@app.get("/api/portfolios/{portfolio_id}/status")
def get_portfolio_status(portfolio_id: int) -> dict:
    with db.get_conn() as conn:
        try:
            st = repo.get_portfolio_status(conn, portfolio_id)
            st["active_task"] = tasking.get_active_portfolio_task(conn, portfolio_id)
            return st
        except KeyError:
            raise HTTPException(404, "组合不存在")


@app.get("/api/portfolios/{portfolio_id}/result")
def get_result(
    portfolio_id: int,
    response: Response,
    method: str | None = None,
    benchmark: str | None = None,
    user: auth.UserContext | None = Depends(auth.optional_user),
) -> dict:
    with db.get_conn() as conn:
        try:
            st = repo.get_portfolio_status(conn, portfolio_id)
        except KeyError:
            raise HTTPException(404, "组合不存在")
        if not repo.can_view_portfolio(conn, portfolio_id, user.user_id if user else None, user.is_admin if user else False):
            raise HTTPException(403, "无权查看该组合")
        if st["status"] == "running":
            raise HTTPException(409, "回测进行中, 请稍后再试")
        if st["status"] == "error":
            raise HTTPException(422, st.get("error") or "回测失败")
        version = repo.get_result_version(conn, portfolio_id)
        key = f"portfolio_result:{portfolio_id}:{method or 'default'}:{benchmark or 'default'}:{version}"
        cached = cache.get_json(key)
        response.headers["ETag"] = f"portfolio-{portfolio_id}-{method or 'default'}-{benchmark or 'default'}-{version}"
        response.headers["Cache-Control"] = "public, max-age=300" if user is None else "private, max-age=60"
        if cached:
            return cached
        result = repo.get_result(conn, portfolio_id, method, benchmark)
        cache.set_json(key, result, 300)
        return result


@app.post("/api/portfolios/{portfolio_id}/recompute")
def recompute(
    portfolio_id: int,
    background_tasks: BackgroundTasks,
    user: auth.UserContext = Depends(auth.require_user),
) -> dict:
    with db.get_conn() as conn:
        try:
            st = repo.get_portfolio_status(conn, portfolio_id)
        except KeyError:
            raise HTTPException(404, "组合不存在")
        if not repo.can_edit_portfolio(conn, portfolio_id, user.user_id, user.is_admin):
            raise HTTPException(403, "无权重算该组合")
        if st["status"] == "running":
            active = tasking.find_active_portfolio_task(conn, portfolio_id)
            if active:
                return {"portfolio_id": portfolio_id, "status": "running", "task_id": active}
            raise HTTPException(409, "回测进行中")
        task_id = _enqueue_backtest(conn, portfolio_id, user.user_id)
        conn.commit()
    _dispatch_backtest(task_id, portfolio_id, background_tasks)
    return {"portfolio_id": portfolio_id, "status": "running", "task_id": task_id}


@app.post("/api/portfolios/{portfolio_id}/copy")
def copy_portfolio(
    portfolio_id: int,
    background_tasks: BackgroundTasks,
    payload: CopyPortfolioIn | None = None,
    user: auth.UserContext = Depends(auth.require_user),
) -> dict:
    if user.user_id is None:
        raise HTTPException(401, "需要登录")
    new_name = payload.name if payload else None
    with db.get_conn() as conn:
        if not repo.can_view_portfolio(conn, portfolio_id, user.user_id, user.is_admin):
            raise HTTPException(403, "无权复制该组合")
        if not user.is_admin:
            limit = repo.get_user_portfolio_limit(conn, user.user_id)
            if limit is not None and repo.count_user_portfolios(conn, user.user_id) >= limit:
                raise HTTPException(403, f"每个用户最多创建 {limit} 个投资组合")
        new_id = repo.copy_portfolio(conn, portfolio_id, user.user_id, new_name)
        task_id = _enqueue_backtest(conn, new_id, user.user_id)
        conn.commit()
    _dispatch_backtest(task_id, new_id, background_tasks)
    return {"portfolio_id": new_id, "status": "running", "task_id": task_id}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str, user: auth.UserContext = Depends(auth.require_user)) -> dict:
    with db.get_conn() as conn:
        try:
            task = tasking.get_task(conn, task_id)
        except KeyError:
            raise HTTPException(404, "任务不存在")
        if not user.is_admin and task.get("owner_user_id") not in (None, user.user_id):
            raise HTTPException(403, "无权查看该任务")
        return task


@app.get("/api/admin/data-sources")
def list_admin_data_sources(_: auth.UserContext = Depends(auth.require_super_admin)) -> dict:
    with db.get_conn() as conn:
        return {"data_sources": repo.list_data_sources(conn)}


@app.get("/api/admin/assets")
def list_admin_assets(_: auth.UserContext = Depends(auth.require_super_admin)) -> dict:
    with db.get_conn() as conn:
        return {"assets": repo.list_admin_assets(conn)}


@app.post("/api/admin/assets/refresh-status")
def refresh_admin_asset_status(_: auth.UserContext = Depends(auth.require_super_admin)) -> dict:
    from .daily_update import refresh_all_asset_status

    with db.get_conn() as conn:
        refresh_all_asset_status(conn)
        conn.commit()
    return {"ok": True}


def _run_ingest_all_background(task_id: str) -> None:
    """无 Redis/Celery 时的降级路径: 同步执行全量拉取(镜像 Celery 任务逻辑)。"""
    from bp_ingest.config import load_config as load_ingest_config
    from bp_ingest import ingest as bp_ingest_run
    from bp_ingest.http_session import install_hardened_session
    from bp_ingest.sources import prewarm_em_code_maps

    try:
        install_hardened_session()
        prewarm_em_code_maps()
        with db.get_conn() as conn:
            tasking.mark_running(conn, task_id, "步骤 1/3：拉取全量增量行情")
            conn.commit()
        app_cfg = load_ingest_config()
        bp_ingest_run.run(app_cfg, symbols=None, refresh_clean=True)
        with db.get_conn() as conn:
            tasking.update_progress(conn, task_id, 3, 3, "全量拉取完成")
            tasking.mark_success(conn, task_id, {})
            conn.commit()
        logger.info("后台全量拉取完成 task_id=%s", task_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("后台全量拉取失败 task_id=%s", task_id)
        try:
            with db.get_conn() as conn:
                tasking.mark_failed(conn, task_id, str(exc))
                conn.commit()
        except Exception:  # noqa: BLE001
            pass


@app.post("/api/admin/assets/sync-all")
def sync_all_admin_assets(
    background_tasks: BackgroundTasks,
    _: auth.UserContext = Depends(auth.require_super_admin),
) -> dict:
    """全量增量拉取所有投资品 + 清洗 + 组合自动排队更新(异步)。"""
    with db.get_conn() as conn:
        task_id = tasking.create_task(
            conn,
            "ingest_all",
            progress_total=3,
            message="已排队全量拉取",
        )
        conn.commit()
    celery_id = tasking.enqueue_task("bp_api.ingest_all", {"task_id": task_id})
    if celery_id:
        with db.get_conn() as conn:
            tasking.set_celery_id(conn, task_id, celery_id)
            conn.commit()
    else:
        background_tasks.add_task(_run_ingest_all_background, task_id)
    return {"task_id": task_id, "status": "running"}


@app.post("/api/admin/portfolios/enqueue-ready")
def enqueue_ready_portfolios_endpoint(
    _: auth.UserContext = Depends(auth.require_super_admin),
) -> dict:
    """手动触发: 刷新资产状态 + 排队所有就绪组合的 T-1 更新。排障兜底。"""
    from .daily_update import enqueue_ready_portfolios, refresh_all_asset_status

    with db.get_conn() as conn:
        refresh_all_asset_status(conn)
        queued = enqueue_ready_portfolios(conn)
        conn.commit()
    return {"queued": len(queued), "portfolios": queued}


@app.post("/api/admin/assets")
def upsert_admin_asset(payload: AssetAdminIn, _: auth.UserContext = Depends(auth.require_super_admin)) -> dict:
    with db.get_conn() as conn:
        if not repo.asset_probe_ok(conn, payload.symbol, payload.source):
            raise HTTPException(400, "请先测试该投资品读取成功后再保存")
        repo.upsert_asset_config(conn, payload)
        repo.refresh_asset_status(conn, payload.symbol, payload.source)
        conn.commit()
    return {"ok": True}


@app.patch("/api/admin/assets/{source}/{symbol}")
def update_admin_asset(source: str, symbol: str, payload: AssetAdminIn, _: auth.UserContext = Depends(auth.require_super_admin)) -> dict:
    payload.source = source
    payload.symbol = symbol
    with db.get_conn() as conn:
        if not repo.asset_probe_ok(conn, symbol, source):
            raise HTTPException(400, "请先测试该投资品读取成功后再保存")
        repo.upsert_asset_config(conn, payload)
        repo.refresh_asset_status(conn, symbol, source)
        conn.commit()
    return {"ok": True}


@app.delete("/api/admin/assets/{source}/{symbol}")
def delete_admin_asset(source: str, symbol: str, _: auth.UserContext = Depends(auth.require_super_admin)) -> dict:
    with db.get_conn() as conn:
        repo.soft_delete_asset(conn, source, symbol)
        conn.commit()
    return {"ok": True}


@app.patch("/api/admin/assets/{source}/{symbol}/selectable")
def set_admin_asset_selectable(
    source: str, symbol: str, payload: AssetSelectableIn,
    _: auth.UserContext = Depends(auth.require_super_admin),
) -> dict:
    """停用/启用该投资品(仅影响 builder 可选性; ingest 仍定时更新)。"""
    with db.get_conn() as conn:
        try:
            repo.set_asset_selectable(conn, source, symbol, payload.selectable)
        except KeyError:
            raise HTTPException(404, "投资品不存在")
        conn.commit()
    return {"ok": True, "selectable": payload.selectable}


@app.post("/api/admin/assets/{source}/{symbol}/probe")
def probe_admin_asset(source: str, symbol: str, _: auth.UserContext = Depends(auth.require_super_admin)) -> dict:
    started = time.perf_counter()
    today = date.today()
    start = today - timedelta(days=365)
    error = None
    rows = 0
    first_date = None
    last_date = None
    try:
        from bp_ingest.sources import fetch_with_fallback

        # 2 次尝试(随机抖动), 抗东财偶发反爬断连; em 被掐断时 fetch_with_fallback 自动降级到 sina/tx
        df = None
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                df = fetch_with_fallback(source, symbol, start, today, {})
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt == 0:
                    time.sleep(random.uniform(1.0, 2.5))
        if last_exc is not None:
            raise last_exc
        rows = int(len(df))
        if rows > 0:
            first_date = str(df["trade_date"].min())
            last_date = str(df["trade_date"].max())
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    with db.get_conn() as conn:
        repo.refresh_asset_status(conn, symbol, source, error=error, probe_ms=elapsed_ms)
        conn.commit()
    if error:
        raise HTTPException(422, error)
    return {
        "ok": True,
        "symbol": symbol,
        "source": source,
        "rows": rows,
        "first_date": first_date,
        "last_date": last_date,
        "elapsed_ms": elapsed_ms,
    }


@app.post("/api/admin/assets/{source}/{symbol}/sync")
def sync_admin_asset(source: str, symbol: str, _: auth.UserContext = Depends(auth.require_super_admin)) -> dict:
    """立即拉取该投资品增量数据并入库+清洗(复用 bp_ingest.run 单标的路径)。"""
    from bp_ingest.config import load_config as load_ingest_config
    from bp_ingest import ingest as bp_ingest_run

    app_cfg = load_ingest_config()
    try:
        results = bp_ingest_run.run(app_cfg, symbols=[symbol], refresh_clean=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"增量拉取失败: {type(exc).__name__}: {exc}")
    res = next((r for r in results if r.symbol == symbol and r.source == source), None)
    if res is None:
        res = next((r for r in results if r.symbol == symbol), None)
    if res is None:
        raise HTTPException(404, "未找到该投资品配置(请确认已保存)")
    if res.status == "error":
        raise HTTPException(422, res.detail or "增量拉取失败")
    return {
        "ok": True,
        "symbol": symbol,
        "source": source,
        "status": res.status,
        "rows": res.rows,
        "detail": res.detail,
    }


@app.delete("/api/portfolios/{portfolio_id}")
def delete_portfolio(portfolio_id: int, user: auth.UserContext = Depends(auth.require_user)) -> dict:
    with db.get_conn() as conn:
        if not repo.can_edit_portfolio(conn, portfolio_id, user.user_id, user.is_admin):
            raise HTTPException(403, "无权删除该组合")
        repo.delete_portfolio(conn, portfolio_id)
    return {"ok": True}
