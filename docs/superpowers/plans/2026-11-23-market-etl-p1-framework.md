# P1 · 统一行情 ETL 框架与四类数据当日就绪 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 `bp_etl` 统一行情 ETL：A 股/港股/ETF/基金净值四类数据在交易日当天完成落库、
覆盖刷新、管理端可见（bfq+hfq；qfq 停用），并完成历史单锚重建与源健康体系。

**Architecture:** 新包 `bp_etl/`（registry + channels + adapters + anchors/writer + quality +
orchestrator + datasets），复用现有行情表与 `/api/v1`/`/api/assets`；PM2 常驻 `bp-etl`
进程按收盘波次调度，轮询追赶至覆盖率达标并**无限重试直到追平**；运行/源健康/质量/backlog 四张新表 + 管理页。

**Tech Stack:** Python 3.13（`.venv`）、psycopg3、requests + curl_cffi、FastAPI、Next.js 16、
PostgreSQL 18 + TimescaleDB、PM2。

**Spec:** `docs/superpowers/specs/2026-11-23-unified-market-etl-design.md`

## Global Constraints

- 只允许 bfq/hfq；qfq 停止拉取且 API 返回 400（历史行保留，不物理删除）。
- 每 (dataset, adjust) 单一锚定源；回退源写入前必须重锚（常数比），source 标注 `:anchored`。
- 未过收盘确认（A/ETF 15:10 CST、HK 16:15 CST）严禁写当日行。
- **无硬停**：任何 dataset 未追平就不得停止；目标时点仅触发升级告警。未达标条目写
  `bp_etl_backlog`，按 10→30 分钟退避无限重试，跨交易日优先重试，直到
  `last_date == 最新可用交易日`。
- ETL 常驻内存 <300MB；写 batch ≤2,000 行；通道并发上限见设计 §7；不得触发服务器 load>2.0。
- 不得提交任何密钥/代理/VLESS 配置；relay 配置只在服务器 `/etc/`。
- 不改现有表主键/字段语义；新迁移编号从 75 起（`ddl/75_etl_health.sql`）。
- 每个 task 完成后必须：`python -m pytest bp_api/tests -q` 与相关新测试全绿；提交信息用仓库
  简短中文祈使句（如 `数据: 新增 bp_etl 通道与限速层`）。
- 现有 `/api/v1/market/*`、资产池、回测行为不得回归（旧测试为硬约束）。

## Review Focus（最容易被忽略、但会咬人的输入/失败模式）

1. **停牌/退市/新上市/无成交代码**：当日无行属合法，覆盖率分母与告警不能误报、不能抛异常。
2. **源返回 HTML/WAF/空 JSON**：必须解析失败即抛错并计入源健康，绝不能把垃圾写进行情表。
3. **除权日 hfq/bfq 比率漂移**：比率门与重锚要在除权日正确放行，否则每天误报或重锚错位。
4. **时间边界**：盘中/未收盘/时区（HK 16:00、期货 15:00）判断错误会永久写入脏收盘价。
5. **并发与重放**：进程重启、重复波次、手动重放必须幂等，覆盖率不得提前标"就绪"。

---

### Task 1: 迁移 75/76（健康表 + qfq 逻辑停用）

**Files:**
- Create: `ddl/75_etl_health.sql`
- Create: `ddl/76_drop_qfq.sql`
- Test: `bonus` 手工在临时库执行两次验证幂等（`scripts/test_migrations.py` 扩展）

**Interfaces:**
- Produces: 表 `bp_etl_run` / `bp_etl_source_health` / `bp_etl_quality_issue` / `bp_etl_dataset_state`
  / `bp_etl_backlog`，字段见设计 §5；`bp_index_config.adjust_modes` 中 qfq 被移除。

- [ ] **Step 1: 写 75 迁移**（CREATE TABLE IF NOT EXISTS + 索引；`bp_etl_run.dataset` 与
  `trade_date`、`bp_etl_source_health` 的 PK 与索引）并附 COMMENT。
- [ ] **Step 2: 写 76 迁移**：`UPDATE bp_index_config SET adjust_modes=array_remove(adjust_modes,'qfq')
  WHERE 'qfq'=ANY(adjust_modes) AND is_deleted=0;`（仅逻辑停用）。
- [ ] **Step 3: 在临时库连跑两次迁移**，验证 exit 0 且重复执行无副作用；记录到 `docs/data/asset-pool-etl.md`。
- [ ] **Step 4: 提交** `数据: 新增 ETL 健康表迁移与 qfq 停用迁移`。

### Task 2: `bp_etl` 骨架（config / registry / 包结构）

**Files:**
- Create: `bp_etl/__init__.py`、`bp_etl/config.py`、`bp_etl/registry.py`、`bp_etl/cli.py`（仅解析骨架）
- Create: `bp_api/tests/test_etl_registry.py`
- Modify: `requirements.txt`（如无新依赖则不动）

**Interfaces:**
- `@dataclass(frozen=True) DatasetSpec`: `name, table, key_column, adjust_modes, anchor: dict[str,str],
  fallback: dict[str, tuple[str,...]], universe: Callable, close_confirm: str('A'|'HK'), deadline_target: time,
  deadline_hard: time, coverage_min: float`
- `@dataclass(frozen=True) SourceSpec`: `name, channel, adapter, adjust_support, rate (req/s), concurrency, batch`
- `load_etl_config() -> EtlConfig`（读 `.env`：`BP_ETL_MODE`、`BP_ETL_CONCURRENCY`、`BP_ETL_RELAY_SG`、
  `BP_ETL_RELAY2`、`BP_ETL_REBUILD_WINDOW` 等；缺省安全值）。
- `REGISTRY: dict[str, DatasetSpec]`；`SOURCES: dict[str, SourceSpec]`；启动时校验引用完整。

- [ ] **Step 1: 写测试** `test_registry_validate_datasets_have_anchor_and_fallback`（缺失锚/回退链报
  `RegistryError`）、`test_config_defaults_are_conservative`。
- [ ] **Step 2: 运行测试确认失败**：`python -m pytest bp_api/tests/test_etl_registry.py -q`。
- [ ] **Step 3: 实现 config/registry**（纯数据类，不连库不联网），并注册四个 P1 dataset 占位
  （`a_stock`/`hk_stock`/`etf`/`fund_nav`）。
- [ ] **Step 4: 测试通过**，提交 `数据: 新增 bp_etl 配置与数据集注册表`。

### Task 3: 通道层（channels）+ 全局限速 + deadline 重试

**Files:**
- Create: `bp_etl/channels.py`、`bp_etl/rate_limit.py`、`bp_etl/retry.py`
- Test: `bp_api/tests/test_etl_channels.py`

**Interfaces:**
- `class Channel`: `get(url, **kw) -> Response`（封装 curl_cffi/requests 会话、Referer/UA、
  direct/relay_sg/relay_prologue 三通道；失败计数、`banned` 标记、冷却时间）。
- `class RateLimiter`: `acquire(source: str) -> None`（全局令牌桶：每 source 每秒上限、
  全局并发上限）；`record_error(source, kind)` 触发指数退避；`snapshot() -> dict`。
- `with_deadline(total_seconds, fn) -> T`：总耗时上限（移植 `bp_ingest/http_deadline.py` 语义，
  防 WAF 慢速滴流挂死线程）。
- `class SourceHealth`: 内存计数（attempts/ok/failed/banned/latency），供 Task 8 落库。

- [ ] **Step 1: 写测试**：令牌桶在 mock clock 下 N 次请求耗时 ≥ N/rate；连续 3 次连接错误后
  `banned=True` 且冷却期内直接抛 `ChannelBanned`；deadline 超时抛 `DeadlineExceeded`。
- [ ] **Step 2: 运行失败**。
- [ ] **Step 3: 实现三通道 + 限速 + deadline**；relay 通道未配置时自动降级 direct 并打 WARNING。
- [ ] **Step 4: 通过后提交** `数据: 新增 bp_etl 通道限速与熔断层`。

### Task 4: Tencent 适配器（qt 批量 / fqkline / hkfqkline / newfqkline 回退）

**Files:**
- Create: `bp_etl/adapters/__init__.py`、`bp_etl/adapters/base.py`、`bp_etl/adapters/tencent.py`
- Test: `bp_api/tests/test_etl_tencent_adapter.py`（离线 fixture，打桩 Channel）

**Interfaces:**
- `class Adapter(Protocol)`: `name`, `capabilities(dataset, adjust) -> bool`,
  `fetch(dataset: str, codes: list[str], adjust: str, start: date, end: date) -> list[Bar]`；
  `Bar = dict(trade_date, open, high, low, close, volume, amount, pct_change, source)`。
- Tencent：`fetch_qt_batch(codes) -> list[Bar]`（60–100 只/请求，bfq 收盘快照）；
  `fetch_kline(codes, adjust, start, end, kind='A'|'ETF'|'HK')`（fqkline → hkfqkline → newfqkline →
  proxy.finance 回退；解析 JSON 失败即 `SourceParseError`）。

- [ ] **Step 1: 测试**：给定 qt 样本文本解析出 3 行 bfq（含 volume 单位股、pct）；给定 WAF HTML
  响应必须抛 `SourceParseError` 且不返回行；HK bfq 走 `fqkline`、HK hfq 走 `hkfqkline` 的路由正确。
- [ ] **Step 2: 失败验证 → 实现 → 通过**。
- [ ] **Step 3: 提交** `数据: 新增腾讯行情适配器`。

### Task 5: Sina 适配器（A 股原始+hfq 因子 / 港股日线）

**Files:**
- Create: `bp_etl/adapters/sina.py`
- Test: `bp_api/tests/test_etl_sina_adapter.py`

**Interfaces:**
- `fetch_a_stock(symbol: str, adjust: 'bfq'|'hfq', start, end) -> list[Bar]`：原始日线来自新浪
  K 线 JSONP；hfq 用新浪 hfq 因子文件复算（**先复算再与库内既有 hfq 尾部重叠日比对**，偏差>0.1%
  抛 `AnchorMismatch`）；实现方式参考 `akshare.stock_zh_a_daily` 的端点与因子公式，但用本包
  Channel（便于通道切换/限速）。
- `fetch_hk_bfq(symbol: str, start, end) -> list[Bar]`（新浪港股日线，服务端直连；失败抛错）。
- 所有日期/数值归一化为 `Bar`，源列 `sina_kline`/`sina_hk_kline`。

- [ ] **Step 1: 测试**：fixture 下 hfq 复算结果与锚定库值一致；因子文件 404/空返回 → `SourceParseError`；
  港股 bfq 解析正确；重叠日偏差超阈值 → `AnchorMismatch`。
- [ ] **Step 2~4: 红→实现→绿→提交** `数据: 新增新浪 A股/港股行情适配器`。

### Task 6: EastMoney 适配器（基金净值直连 + push2his 经 relay 通道）

**Files:**
- Create: `bp_etl/adapters/eastmoney.py`
- Test: `bp_api/tests/test_etl_em_adapter.py`

**Interfaces:**
- `fetch_fund_rank(session) -> list[FundNavRow]`（rankhandler 42 页×500，`em_rankhandler`）；
- `fetch_fund_nav_lsjz(code, days=40) -> list[FundNavRow]`（`em_lsjz`，补缺用）；
- `fetch_kline(secid, adjust, start, end) -> list[Bar]`：只允许 `relay_sg`/`relay_prologue` 通道；
  直连通道探测到封禁时立即标记该通道不可用（返回 `ChannelBanned`）。
- 解析失败/非 JSON 一律 `SourceParseError`；`qfq` 参数直接断言拒绝（`ValueError`）。

- [ ] **Step 1: 测试**：基金行解析（code/date/nav/acc_nav）；EM kline 在 direct 通道必须抛
  `ChannelBanned`（fixture 关闭），在 relay 通道返回 Bar；qfq 调用抛 `ValueError`。
- [ ] **Step 2~4: 红→实现→绿→提交** `数据: 新增东财基金/行情适配器（relay 通道）`。

### Task 7: 锚定 + 写入器 + coverage 增量刷新

**Files:**
- Create: `bp_etl/anchors.py`、`bp_etl/writer.py`、`bp_etl/coverage.py`
- Test: `bp_api/tests/test_etl_writer.py`（打桩 psycopg，或使用 `bp_api/tests/conftest.py` 夹具）

**Interfaces:**
- `reanchor(anchor_bars, fallback_bars, anchor_source) -> list[Bar]`：最近 3 个重叠日中位比率缩放
  OHLC，`source='{fallback}:anchored'`；无重叠日时禁写并抛 `NoOverlapError`。
- `write_bars(conn, dataset: DatasetSpec, rows: list[Bar]) -> int`：UPSERT 幂等；自动补
  `pct_change`（源无值时按库里 prev_close 计算）；写后返回行数；同事务内不改其它 dataset。
- `refresh_coverage(conn, dataset: DatasetSpec, codes: list[str]) -> int`：增量 UPSERT
  `bp_asset_coverage`（stock/etf/fund/index 映射由 DatasetSpec.coverage_kind 决定），不再 TRUNCATE。
- `full_coverage_reconcile(conn) -> dict`：23:50 全量校准（仅异常时使用，流式 SQL）。

- [ ] **Step 1: 测试**：重锚后收益率与锚定源一致（误差 <1e-9）、绝对价按比率缩放；UPSERT 幂等
  （同批跑两次行数不变）；pct 计算与既有规则一致；coverage 增量不删除其它 kind 行。
- [ ] **Step 2~4: 红→实现→绿→提交** `数据: 新增锚定写入与增量覆盖快照`。

### Task 8: 质量门 + 健康落库

**Files:**
- Create: `bp_etl/quality.py`、`bp_etl/health.py`
- Test: `bp_api/tests/test_etl_quality.py`

**Interfaces:**
- `evaluate(dataset, date, rows, expected_universe, conn) -> QualityReport(ok, coverage, issues)`：
  实现设计 §8 的 7 条门（行数、OHLC、pct、交叉源、比率漂移、新鲜度、无未来日）。
- `record_run(conn, run: RunRecord)`、`record_source_health(conn, stat)`、`record_issue(conn, issue)`；
  `upsert_dataset_state(conn, dataset, last_success_date, run_id)`。

- [ ] **Step 1: 测试**：OHLC 非法行被拒并记 issue；覆盖率 97% 触发不达标；除权日（fixture 里
  ratio 变化）不被误报；未来日期行被拒。
- [ ] **Step 2~4: 红→实现→绿→提交** `数据: 新增 ETL 质量门与运行健康落库`。

### Task 9: 编排器（波次/轮询追赶/截止/锁/幂等/重放）

**Files:**
- Create: `bp_etl/orchestrator.py`
- Test: `bp_api/tests/test_etl_orchestrator.py`（假时钟 + FakeAdapter/FakeWriter）

**Interfaces:**
- `class Orchestrator`: `run_dataset(dataset, trade_date, now, force=False) -> RunResult`；
  `service()`（常驻：按 DatasetSpec 时间表触发，`pg_try_advisory_lock` 防重入）；
  `run_wave(dataset, wave)`；`replay(dataset, date, wave)`。
- 波次策略：目标时间起，每波后计算覆盖；未达标则 +10min（退避上限 30min）**无限**再跑，
  直到追平（无硬停）；未达标条目 upsert 到 `bp_etl_backlog`，跨交易日优先重试；
  每波写 `bp_etl_run`；达标写 `bp_etl_dataset_state.last_success_date` 并从 backlog 清除。

- [ ] **Step 1: 测试**：假时钟下 15:30 第一波、未达标 → 15:40 第二波且**永不停止**（run 状态
  `catching_up`，未达标条目进 backlog，跨交易日优先重试）；同一 dataset 并发调用第二个拿不到锁
  直接返回 `Skipped`；重放同波次幂等。
- [ ] **Step 2~4: 红→实现→绿→提交** `数据: 新增 ETL 波次编排与重放`。

### Task 10: 四类 dataset 与 CLI

**Files:**
- Create: `bp_etl/datasets/a_stock.py`、`hk_stock.py`、`etf.py`、`fund_nav.py`；
  `bp_etl/cli.py`（`run/service/rebuild/verify/health` 子命令）
- Test: `bp_api/tests/test_etl_datasets.py`

**Interfaces:**
- 每个 dataset 提供 `universe(conn) -> list[str]`、`plan(today, now) -> list[WavePlan]`、
  `fetch(wave, codes) -> list[Bar]`（组合 Task 4–6 适配器 + 锚定 + 写入 + 质量门）。
- CLI：`python -m bp_etl run --dataset a_stock --date 2026-11-23`、`service`、`rebuild`、`verify`、`health`。

- [ ] **Step 1: 测试**：a_stock 9:xx/15:30 时间窗不产出；15:11 后 bfq 波次生成；hk_stock 16:15 前
  不写；fund_nav 多波 6 次且只补缺；ETF hfq 回退链在腾讯全失败时调用 EM-relay。
- [ ] **Step 2~4: 红→实现→绿→提交** `数据: 新增四类行情 dataset 与 CLI`。

### Task 11: 历史单锚重建 + 校验报告

**Files:**
- Create: `bp_etl/rebuild.py`（或并入 cli）、`scripts/verify_etl_rebuild.py`
- Test: `bp_api/tests/test_etl_rebuild.py`（小样本打桩）
- Create: `docs/superpowers/reports/2026-11-2x-etl-rebuild-verification.md`（执行阶段产出）

**Interfaces:**
- `rebuild(dataset, since=date(2020,1,1), workers, resume=True)`：按 symbol 分页拉全历史（A: 新浪
  原始+hfq 因子；HK: 新浪 bfq + 腾讯 hfq；ETF: 腾讯 bfq/hfq），断点续跑（已有区间跳过），
  分批 2,000 行写入；结束后 `verify_rebuild()` 输出：每 dataset 覆盖数/区间、hfq 比率常数性
  （非除权日 r 变化率<0.01%）、新旧序列收益相关性 >0.9999、与外部源抽样比对 N/N。
- 重建期双写/保留旧行；校验通过后才切换锚定优先级（由环境/注册表开关控制）。

- [ ] **Step 1: 测试**：断点续跑（已完整 symbol 不再发请求）；verify 在比率漂移 fixture 上报错。
- [ ] **Step 2~4: 红→实现→绿**。
- [ ] **Step 5: 在服务器夜窗执行真实重建**（A/HK/ETF），产出校验报告；提交 `数据: 完成 A股/港股/ETF 单锚历史重建与校验`。

### Task 12: 管理端数据健康 API + 页面

**Files:**
- Create: `bp_api/data_health.py`（register_routes）
- Modify: `bp_api/main.py`（注册路由）
- Create: `web/app/admin/market-data/page.tsx`、`web/components/admin/DataHealthPanel.tsx`
- Modify: `web/app/admin/assets/page.tsx`（顶部入口卡片）、`web/lib/api.ts`（类型）
- Test: `bp_api/tests/test_data_health_api.py`；web 不新增测试文件（typecheck/build 验收）

**Interfaces:**
- `GET /api/admin/data-health/overview` → `{datasets:[{name,last_date,coverage,target,hard_deadline,
  ready,last_run}], generated_at}`；`GET /api/admin/data-health/runs?dataset=&limit=`；
  `GET /api/admin/data-health/sources`；`POST /api/admin/data-health/replay`
  （body: dataset/date/wave，写审计日志）；全部 `Depends(auth.require_super_admin)`。
- 页面仅管理员可见；复用 `getToken()` 请求；红黄绿状态 + 最近运行表 + 源矩阵 + 问题列表。

- [ ] **Step 1: 测试**：未登录 401、非超管 403、超管 200 且字段完整；replay 参数校验 400。
- [ ] **Step 2~4: 红→实现→绿→typecheck/build**；提交 `数据: 新增行情数据健康 API 与管理页`。

### Task 13: qfq 停用（API / 前端 / ETL / 配置）

**Files:**
- Modify: `bp_api/public_api.py`（`ADJUST_MODES={bfq,hfq}`、`_parse_adjust` 对 qfq 报
  `invalid_parameter: qfq 已停用`）、`bp_api/quote_store.py`（拒绝 qfq 调用）
- Modify: `web/lib/api.ts`、`web/components/UnifiedAssetsPanel.tsx`、`web/app/admin/assets/page.tsx`、
  builder 相关 adjust 选项（如有）→ 只留 bfq/hfq
- Modify: `bp_api/tests/test_public_api.py`、`test_market_api.py`（更新期望）
- Test: 新增 `test_qfq_retired`

- [ ] **Step 1: 测试**：`?adjust=qfq` 返回 400 且 error.code=`invalid_parameter`；`bfq/hfq` 正常；
  前端选项只含 bfq/hfq（typecheck 后人工核对）。
- [ ] **Step 2~4: 红→实现→绿→提交** `数据: 停用前复权口径（API 与前端隐藏）`。

### Task 14: 调度接入与部署（PM2 bp-etl 替代 crontab）

**Files:**
- Modify: `deploy/ecosystem.config.cjs`（新增 `bp-etl` 进程：`.venv/bin/python -m bp_etl service`）
- Create: `scripts/install_etl_cron_cleanup.sh`（注释/删除 v3 五条 root crontab 的可回滚脚本）
- Modify: `deploy/OPS.md`、`docs/data/asset-pool-etl.md`、`docs/data-sources.md`
- Test: 服务器灰度：先 `BP_ETL_MODE=shadow`（只跑不写）观察 1 个交易日 → 切 `on`

**Interfaces:**
- `BP_ETL_MODE=off|shadow|on`：off=不执行；shadow=拉取+质量+报告但不写库；on=正常写库。
- 部署顺序：部署代码 → 启动 bp-etl（off）→ 手工 `run` 验证 → 切 on → 注释旧 crontab →
  次日核对 → 清理。回滚：切 off + 恢复 crontab（脚本自动备份）。

- [ ] **Step 1: 修改 ecosystem 与安装脚本**；`pm2 start` 灰度。
- [ ] **Step 2: 手工跑四类 dataset 的 run 并核对 DB 行数/覆盖**；记录到部署文档。
- [ ] **Step 3: 切 on、停旧 cron；提交** `数据: 接入 bp-etl 常驻调度并停用旧行情 cron`。

### Task 15: Phase 0 时点研究 + 验收测试 + 文档

**Files:**
- Create: `scripts/etl_source_timing_report.py`（读 `bp_etl_run` 统计每源首次达标时刻）
- Create: `bp_api/tests/test_etl_acceptance.py`（集成：临时库 + 小 universe 走完整波次）
- Create: `docs/superpowers/reports/2026-11-2x-source-timing.md`（P0 产出）
- Modify: `docs/API.md`、`docs/data/asset-pool-etl.md`

**Interfaces:**
- `timing_report(days=5) -> dict[source, {p50_first_ready, p95_first_ready}]`；用于校准 §2.1 SLA。
- 验收命令：`python -m pytest bp_api/tests -q`、`cd web && npm run typecheck && npm test && npm run build`、
  `python -m bp_etl verify --dataset a_stock --date <last_trading_day>`。

- [ ] **Step 1: 写 timing report 脚本 + 报告模板**（不依赖外部网络）。
- [ ] **Step 2: 写 acceptance 集成测试**（建临时 schema/回滚事务；断言：未收盘不写、达标才置
  `last_success_date`、重跑幂等、coverage 当日可见、**源晚发布 2h 时持续追赶直到追平**）。
- [ ] **Step 3: 全量回归 + 服务器 dry-run 记录**；提交 `文档: P1 验收与时点研究报告`。

---

## 自检（Self-Review 结论，写入计划时已核对）

- 规格覆盖：设计 §3/§4/§5/§6/§7/§8/§11/§12/§13(P1) 均有对应 task（1–15）；
  §9/§10（P2）不在本计划，见 P2 计划。
- 类型一致性：`Bar`/`Bar` 字段、`DatasetSpec` 字段在 Task 2 定义、Task 4–10 复用；
  `RunResult`/`QualityReport` 在 Task 8/9 定义后 Task 10 消费。
- 无占位/空泛步骤（"处理边界"类已落到具体断言）。
- Review Focus 5 条均已在具体 task 的测试步骤中钉住。
