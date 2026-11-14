# 指数估值系统 · 代码审计标准

> 版本：2026-11-14 ｜ 适用：`bp_api/`、`bp_ingest/`、`web/`、`ddl/` 全部变更 ｜ 上游：`CLAUDE.md`、`AGENTS.md`、`13-acceptance-and-test.md`
> 目标：让审查可执行、可举证、可阻断；每条意见必须指明「看什么、为什么、怎么改」。风格偏好不算缺陷，正确性/数据口径/安全/性能才算。

## 1. 通用门禁（全部通过才进入人工审查）

| # | 门禁 | 命令 | 通过标准 | 阻断 |
|---|---|---|---|---|
| 1 | 后端全量测试 | `python -m pytest bp_api/tests -q` | 0 failed；用例数不低于主干基线（当前收集 266） | 是 |
| 2 | 变更定向测试 | `python -m pytest <新增/受影响测试文件> -q` | 新增用例全绿；修复类 PR 必带回归用例 | 是 |
| 3 | 前端单元测试 | `cd web && npm test` | vitest 全绿；新增纯函数必须有 `.test.ts` | 是 |
| 4 | TypeScript 静态检查 | `cd web && npm run typecheck` | exit 0；仓库无 eslint，`tsc --noEmit` 是唯一静态门禁 | 是 |
| 5 | 前端构建 | `cd web && npm run build` | exit 0；CI 同口径（Next 16 + Turbopack） | 是 |
| 6 | 包/路由冒烟 | `python -m bp_ingest --help`；`python -c "from bp_api.main import app; print(len(app.routes))"` | 均 exit 0 | 是 |
| 7 | 迁移幂等 | 同一迁移脚本连续执行 3 次 | 每次 exit 0；表/约束/行数不变 | 是 |
| 8 | 密钥扫描 | `gitleaks detect --no-git --redact`（或等价扫描） | 0 条高置信泄漏 | 是 |
| 9 | 禁止新增 lint 错误 | 人工检查 `@ts-ignore`、`any`、未使用变量 | 新增 `@ts-ignore` 必须附 issue 与移除期限 | 否 |
| 10 | CI | `.github/workflows/ci.yml` 两个 job | backend + frontend 全绿 | 是 |

## 2. 分层审计要点

### 2.1 后端 API（`bp_api/*.py`、`repositories*.py`）

| # | 检查项 | 看什么 | 为什么 | 怎么改 |
|---|---|---|---|---|
| 1 | 请求路径永不计算 | 路由函数内是否循环算分位/回测/相关性 | `/cffex`、`/crypto` 的铁律；请求路径计算会拖垮 P99 | 计算移到 `bp_ingest`/Celery，路由只读预计算表 |
| 2 | 事务边界 | `with db.get_conn()` 内是否显式 `conn.commit()`；是否有长事务包住 HTTP | psycopg3 默认不自动提交；漏提交导致任务行不可见 | 写操作后显式 commit；只读不 commit；缩小事务范围 |
| 3 | 鉴权与越权 | 是否挂 `require_user`/`require_super_admin`/`optional_user`；是否校验 owner | 组合/持仓/token 均可横向越权 | 加依赖；资源查询带 `owner_user_id`；越权返回 403，不泄漏资源存在性 |
| 4 | SQL 注入 | 是否 `%s` 参数化；动态表名/列名是否白名单 | f-string 拼 SQL 可直接注入 | 值走参数；标识符用固定映射；禁止用户输入进 SQL 结构 |
| 5 | NaN/Inf 清洗 | `Json()` 前是否走 `_json_safe`；权重是否 `_round` | psycopg 拒绝 `NaN/Infinity` token，会 500 | 所有 JSON 实参清洗；数值权重保留 6 位 |
| 6 | 契约与分页 | 是否有 Pydantic 响应模型；`limit` 是否有上限 | 防空字段漂移与全表导出 | 明确 response_model；分页上限（如 5000 行）；CSV 流式输出 |
| 7 | 错误码 | 400/401/403/404/409/422/429/500 是否稳定 | 前端与 API 客户依赖错误码 | 统一 `{"error":{"code","message"}}`；不返回堆栈 |
| 8 | 缓存键与失效 | key 是否含全部参数 + result version；写后是否失效 | 参数漏进 key 会串结果 | key 哈希化；写路径 `cache.invalidate_*`；ETag 带版本 |
| 9 | 任务派发 | 是否「先 commit `bp_task`，再 dispatch」 | worker 看不到未提交任务 | 提交后派发；`inline`/Redis 缺失降级 `BackgroundTasks` |
| 10 | 日志脱敏 | 是否打印 Authorization/Cookie/token/密码 | 日志是二次泄漏源 | 只打印 token prefix；请求体脱敏；统一 request_id |

### 2.2 数据入库（`bp_ingest/`）

| # | 检查项 | 看什么 | 为什么 | 怎么改 |
|---|---|---|---|---|
| 1 | 标准 schema | 适配器输出是否含 `trade_date/open/high/low/close/volume`，close 非空 | 下游清洗/回测依赖统一列 | 在 `sources.py` 归一化；close 缺失直接丢弃该行 |
| 2 | 复权维度 | `_UPSERT_SQL` 的 conflict target、`row_hash` 表达式是否含 `adjust` | 不含则三口径互相覆盖 | PK/唯一键/`row_hash` 全部加 `adjust` |
| 3 | 降级链 | `fetch_with_fallback` 是否识别连接级错误；是否记录实际 source | 东财反爬时需切新浪/腾讯 | `_is_conn_error` 判定；失败重试；落库记录真实 source |
| 4 | 收盘确认 | 今日行是否在 15:10 后才入库 | 盘中快照污染历史 | 用 `BP_CLOSE_CONFIRM_HHMM` 门控；未确认不落「今日」 |
| 5 | effective_td | 是否要求当日所需标的齐全（NaN 过滤）才推进 | 放宽会制造「假新鲜」 | 复用 `pick_effective_trade_date`；缺一即 hold-back |
| 6 | COUNT 分级 | 热路径是否 `with_count=False`；COUNT 是否只在 `refresh_asset_status(with_count=True)` | 每次 ingest 全表 COUNT 会拖慢并锁表 | 热路径只取 MAX；管理端「刷新状态」才 COUNT |
| 7 | 汇率折算 | 非 CNY 是否按 `fx_sina` 折算；crypto/cffex 是否保持 USD | 口径混用导致收益/回撤错 | 无汇率日不产出清洗行；写 `fx_rate` 审计列 |
| 8 | PiT 语义 | 是否保留 `captured_at`/`raw`；历史值是否被 UPDATE 覆盖 | 供应商修订会改写历史，破坏可回溯 | 只追加；修订写新行；`captured_at` 不重写 |
| 9 | 失败隔离 | 单标的失败是否阻塞整批；是否写 `bp_data_refresh_run` | 一个坏源拖垮全量 | 单标的 try/except；失败记 error；下游跳过该标的 |
| 10 | 幂等与日期 | 重跑是否 `ON CONFLICT`；`start_date` 是否只在首拉写 | 重跑产生重复行；伪造日期无法复现 | 幂等 upsert；`start_date IS NULL` 时才写；禁止用 `MIN(trade_date)` 回填 |

### 2.3 量化（`bp_api/quant/`）

| # | 检查项 | 看什么 | 为什么 | 怎么改 |
|---|---|---|---|---|
| 1 | 无未来函数 | 权重是否次日生效；滚动矩是否只用前缀 | 未来数据泄漏会让回测虚高 | 保持 cum1/cum2 前缀和；新增 `test_no_lookahead` 类用例 |
| 2 | effective_start | `min_window` 是否生效；晚上市资产是否权重 0 | 拖后整体起点会低估策略 | 复用引擎判据；不足窗口不参与 |
| 3 | coverage 唯一来源 | 是否调用 `quant/coverage.py` | 前端近似 `first_clean_date` 会漏报 | 只消费 `compute_coverage`/`_coverage_rows`；禁止另写判据 |
| 4 | 优化器数值 | 零方差/NaN/不收敛是否兜底；权重和是否为 1 | 退化资产会产出 NaN 权重 | CCD/SLSQP 后清洗；`abs(Σw-1)<1e-6`；失败回退等权 |
| 5 | 再平衡与成本 | 漂移阈值是否绝对值；印花税是否仅卖出 | 成本口径错会系统性高估收益 | 任一资产偏离 >`rebalance_band` 才整体回目标；费用公式单测锁定 |
| 6 | 基准注册表 | 前后端 `BENCHMARKS`/`BENCHMARK_OPTIONS` 是否一致 | 基准缺腿会导致归因错 | 后端注册表为唯一源；前端常量同步；按日再平衡合成 |
| 7 | 分位公式 | 是否 `(count<=x-0.5*count==x)/N`；样本门槛 120 | 公式漂移会改变所有估值结论 | 唯一入口 `quant/valuation.py`；金标准测试锁定 |
| 8 | ERP 同日 | 股息率与 `bond10y` 是否同日 | 跨日相减无经济含义 | 同日缺失即 `NULL`；不 forward-fill |
| 9 | 复权过滤 | 读价格面板是否显式带 `adjust` | 隐式默认会读到重复行 | 按组合资产声明口径过滤；CFFEX/crypto/OTC 显式 `bfq` |
| 10 | 并行与降级 | Celery 内是否回退 `ThreadPoolExecutor`；进程池是否可序列化 | 守护进程用进程池会崩 | 检测运行环境；任务参数保持可 pickle |

### 2.4 前端（`web/`）

| # | 检查项 | 看什么 | 为什么 | 怎么改 |
|---|---|---|---|---|
| 1 | 常量同步 | `METHOD_OPTIONS`/`BENCHMARK_OPTIONS`/`OTC_*`/`adjust` 是否与后端一致 | 前后端枚举漂移会 422 | 前端常量作为镜像；PR 同时改两侧并加测试 |
| 2 | 图表主题 | 是否只经 `web/lib/chart-theme.ts` | 散落颜色破坏设计系统与暗色模式 | 统一 token；涨跌色仅方向性使用 |
| 3 | 反馈与危险操作 | 是否 `window.alert/confirm`；是否 sonner/AlertDialog | 阻塞式弹窗不可测试且违反规范 | 改 sonner toast；危险确认用 AlertDialog |
| 4 | Server/Client 边界 | ECharts 是否 `dynamic(...,{ssr:false})`；是否在服务端用浏览器 API | hydration mismatch/构建失败 | 图表客户端岛；`typeof window` 不用于渲染分支 |
| 5 | 缓存链 | `cacheLife("hours")` 与 `cacheTag`/`revalidateTag(tag,"hours")` 是否一致 | profile 不一致会失效不到 | 两处都传 `"hours"`；写后调用失效端点 |
| 6 | 可访问性 | label/aria/键盘/focus/对比度 | 表格图表不可键盘操作 | 补 `aria`、焦点环、方向键；axe 0 critical |
| 7 | 响应式 | 390/768/1024/1440 是否横向溢出 | 移动端表格是高频回归点 | 表格容器 `overflow-x:auto`；>300 行虚拟滚动 |
| 8 | 状态完备 | loading/empty/error/stale 是否有 UI | `null/NaN` 直接渲染是事故 | 统一占位「—」；错误态可重试；stale 徽章 |
| 9 | API 客户端 | `web/lib/api.ts` 是否强类型；错误是否归一 | `any` 会放过字段漂移 | 类型化 response；统一抛 `ApiError`；AbortController |
| 10 | Bundle 预算 | 单路由 First Load JS 增量；是否引入大依赖 | 估值页首屏预算是硬指标 | 动态 import；服务端组件；超 15KB 需说明 |

### 2.5 迁移（`ddl/`）

| # | 检查项 | 看什么 | 为什么 | 怎么改 |
|---|---|---|---|---|
| 1 | 编号只增不改 | 是否修改已应用 `NN_*.sql` | 生产已执行，改了也不会生效 | 新建下一个编号；旧文件保持只读 |
| 2 | schema 同步 | `ddl/schema.sql` 是否含同一变更 | 全新环境只跑 schema | 迁移与基线同 PR 更新 |
| 3 | 幂等 | 是否 `IF NOT EXISTS`/DO block；重复执行 exit 0 | 部署可能重试 | 所有 DDL 幂等；重复执行验证 3 次 |
| 4 | 回滚 | 是否提供反向 DDL；是否删数据 | 上线失败需快速回退 | 只删列/恢复旧约束；不删行；回滚脚本实测 |
| 5 | Timescale | 主键是否仍含分区列 `trade_date`；chunk 是否兼容 | 改 PK 可能无法执行 | PK 保留 `trade_date`；低峰执行；先 `pg_dump` |
| 6 | 生成列 | `row_hash` 表达式是否含新维度；是否触发表重写 | 表达式漏列会撞唯一性 | 重建生成列；评估重写耗时；必要时降级为删除 |
| 7 | 回填语义 | ETF 是否回填 `hfq`；是否一律 `bfq` | 存量 ETF close 本身是后复权 | 按真实 source 打标；迁移前后 NAV 对比 |
| 8 | 约束/索引 | FK 的 `ON DELETE`；新查询是否有索引 | 缺索引导致 P99 超标 | 补 `(index_code,trade_date)` 等索引；CASCADE 明确 |
| 9 | 部署边界 | `deploy/deploy.sh` 是否执行迁移 | 自动迁移可能重复/锁表 | 迁移单独人工执行；deploy 不跑迁移 |
| 10 | 新旧库对账 | 全新库 ×3 后与生产 `pg_dump --schema-only` 对比 | schema 与迁移漂移常见 | 临时库验证；字段/约束/索引零差异 |

## 3. 本项目特有硬规则（一票否决）

| # | 规则 | 原因 | 审查检测 | 修复 |
|---|---|---|---|---|
| 1 | 请求路径永不计算 | 看板 P99 与稳定性 | 路由内出现 pandas/numpy/循环聚合 | 移到 ingest/worker，落预计算表 |
| 2 | effective_td hold-back | 防「假新鲜」 | 是否过滤 NaN、是否要求标的齐全 | 缺一即停在上一个完整日 |
| 3 | COUNT 分级不变式 | 避免全表 COUNT 拖垮热路径 | 热路径是否出现 `count(*)`/`with_count=True` | 只保留 MAX；COUNT 仅管理端刷新 |
| 4 | NaN/Inf 清洗 | psycopg 拒绝 NaN token | `Json()`/权重是否未清洗 | `_json_safe` + `_round` |
| 5 | revalidateTag profile 一致 | Next 16 不匹配则失效不到 | `cacheLife` 与 `revalidateTag` 第二参数 | 统一 `"hours"` |
| 6 | 无未来函数 | 回测结论可信度 | 是否用到 `t` 之后收益/右锚 | 前缀和；次日生效；篡改未来测试 |
| 7 | 缓存失效链完整 | 重算后前端仍显示旧值 | ingest→invalidate→revalidate 是否闭环 | 后端失效 + `POST /api/revalidate/*` |
| 8 | 只读 `bp_quote_clean` | 单一事实源 | 回测/coverage 是否直连 `bp_index_quote_daily` | 改读清洗表；原始表只写入 |
| 9 | adjust 显式过滤 | 多口径并行防串行 | 查询是否依赖默认值 | 每个读取点显式 `adjust=...` |
| 10 | PiT 只追加 | 历史可回溯 | 是否 UPDATE 历史估值行 | 新行 + `captured_at`；保留 `raw` |
| 11 | Session 路由顺序 | 登录 404 | 代理是否把 `/api/session` 转给 FastAPI | Next Route Handler 优先；rewrite 后置 |
| 12 | 组合参数单一来源 | 避免死配置 | 是否读环境变量兜底 risk_free/lookback/band | 只读组合行；删除环境变量回退 |

## 4. 数据迁移审计

| # | 审计项 | 操作 | 通过标准 |
|---|---|---|---|
| 1 | 编号 | `git diff --name-only origin/main...HEAD -- ddl/` | 只新增未应用编号；无旧文件改动 |
| 2 | 基线 | 检查 `ddl/schema.sql` 同 PR 更新 | 全新库只跑 schema 即得到目标结构 |
| 3 | 幂等 | 同一脚本连续执行 3 次 | 每次 exit 0；`count(*)` 与约束不变 |
| 4 | 回滚 | 执行 `ddl/rollback/NN_*.down.sql` | 列/约束恢复；数据行数不变；旧读路径可用 |
| 5 | 数据回填 | 迁移前后按 source/adjust 分组计数 | ETF `hfq` 行数符合预期；无「一律 bfq」 |
| 6 | 约束 | `\d+` 检查 PK/UNIQUE/CHECK/FK | 与 `06-data-model-v3.md` 一致 |
| 7 | 性能 | `EXPLAIN (ANALYZE, BUFFERS)` 新查询 | 走索引/分区裁剪；无大表 Seq Scan |
| 8 | 备份 | 上线前 `pg_dump` + 恢复演练 | 备份可恢复；记录校验和 |
| 9 | 新旧库对账 | 临时库跑 schema×3 + 迁移×3，对比生产 schema | 字段/约束/索引零差异 |
| 10 | 部署边界 | 检查 `deploy/deploy.sh` | 不包含迁移执行 |

幂等验证命令：`psql "$DSN" -v ON_ERROR_STOP=1 -f ddl/51_quote_adjust_dimension.sql && psql "$DSN" -v ON_ERROR_STOP=1 -f ddl/51_quote_adjust_dimension.sql && echo "exit=$?"`。期望第二次仍 `exit=0`，且 `SELECT count(*) FROM bp_quote_clean` 与执行前一致。回滚后必须重跑 `python -m pytest bp_api/tests/test_quote_adjust.py -q`。

## 5. 安全审计

| # | 检查项 | 看什么 | 通过标准 |
|---|---|---|---|
| 1 | 密钥不入 git/库 | `.env` 是否被跟踪；代码/迁移是否硬编码 | `.gitignore` 覆盖；gitleaks 0 条 |
| 2 | JWT 强度 | `BP_JWT_SECRET` 长度与来源 | ≥32 字符；缺失启动即失败 |
| 3 | Token 存储 | 是否只存 `sha256(secret+pepper)`；是否存明文 | 只有 `token_hash` + `prefix`；无明文列 |
| 4 | Token 生命周期 | `expires_at`/`revoked_at`/`last_used_at`/scopes | 过期/撤销即 401；scopes 精确校验 |
| 5 | SQL 注入 | 值是否参数化；标识符是否白名单 | 无 f-string/字符串拼接 SQL |
| 6 | 越权 | owner/scopes/超管校验 | 跨用户访问 403；不泄漏资源存在性 |
| 7 | 限频 | 默认 60 req/min、burst 10 | 超限 429 + `Retry-After` |
| 8 | 内部端点 | `X-Internal-Token`/HMAC/nonce | 无 token 401；重放不产生重复行 |
| 9 | Cookie | `bp_session` 是否 httpOnly/secure/sameSite | 三项齐全；不写入 localStorage |
| 10 | 日志脱敏 | Authorization/Cookie/token/密码 | 日志只留 prefix/request_id |
| 11 | 依赖漏洞 | `pip-audit` / `npm audit --omit=dev` | 无 high/critical；有则附豁免理由 |
| 12 | CORS/代理 | 允许源是否白名单；`/api/session` 路由顺序 | 不允许 `*` 携带凭证；登录不 404 |

## 6. 性能审计

| # | 检查项 | 方法 | 阈值/通过标准 |
|---|---|---|---|
| 1 | N+1 查询 | 审查循环内是否逐资产查询；统计单请求 SQL 数 | 单请求查询数固定；批量用 `= ANY(%s)` |
| 2 | 索引 | `EXPLAIN (ANALYZE, BUFFERS) <SQL>` | 走 Index/Bitmap Scan；大表无 Seq Scan |
| 3 | 分区裁剪 | Timescale 查询是否带时间谓词 | 只扫必要 chunk；无全表扫描 |
| 4 | 响应体 | 分页/字段选择/CSV 流式 | 单页 ≤5000 行；JSON 不重复冗余字段 |
| 5 | 缓存 | Redis/Next 命中率 | ≥90%；失效后一次请求内更新 |
| 6 | Bundle | `npm run build` 路由表对比主干 | 单路由 First Load JS 增长 ≤15KB；共享 chunk ≤10KB |
| 7 | 图表/表格 | ECharts 动态导入；>300 行虚拟滚动 | 首屏不加载图表库；500 行滚动 ≥55fps |
| 8 | TTFB/P99 | 见 `13-acceptance-and-test.md` 第 6 节 | 首页 <400ms；详情 <500ms；API P99 <300ms |
| 9 | 连接池 | 是否复用 `db.get_conn()`；是否长连接泄漏 | max 8；请求结束归还 |
| 10 | 内存/定时器 | 客户端是否泄漏 interval/listener | 卸载清理；无重复订阅 |

Bundle 增量检查：`git checkout main && (cd web && npm run build) > /tmp/build-base.txt`，再对 PR 分支执行同命令，逐路由比较 `First Load JS`；超过 15KB 必须在 PR 中说明并给出拆分方案（动态 import/服务端组件/移除依赖）。

## 7. Review 流程

| 角色 | 谁审 | 必看内容 | 批准条件 |
|---|---|---|---|
| 作者自审 | PR 作者 | 门禁、diff、证据完整性 | 全部证据齐全 |
| 同行审查 | 任意熟悉该层的工程师 | 正确性、可读性、测试 | 无 blocker/major |
| 领域审查 | 量化/数据负责人 | `bp_api/quant/`、`bp_ingest/`、复权/分位 | 2 人批准（含领域负责人） |
| 迁移审查 | DBA/后端负责人 | `ddl/`、回滚、幂等、锁 | 2 人批准；临时库演练通过 |
| 安全审查 | 超管/安全负责人 | `auth.py`、token、内部端点 | 超管批准 |
| 前端审查 | 前端负责人 | 断点、a11y、图表、bundle | 4 断点截图 + axe 通过 |

审查顺序：1）读 PR 描述与影响面；2）确认 CI 全绿；3）必看 diff：`ddl/`、`ddl/schema.sql`、`bp_api/repositories*.py`、`bp_api/quant/`、`bp_api/auth.py`、`web/lib/api.ts`、`web/next.config.mjs`、`.github/workflows/ci.yml`；4）核对证据（测试输出、`EXPLAIN`、NAV 对比、截图）；5）按 `[blocker]/[major]/[minor]/[nit]` 标注；6）blocker=0 才批准。禁止自批、红 CI 合并、审查后 force-push 不重新审查。SLA：普通 PR 1 个工作日；迁移/量化 2 个工作日。合并后 2 小时观察错误率、P99、数据覆盖率。

## 8. PR 模板（可直接复制）

```markdown
## 变更摘要
<!-- 一句话说明行为变化；关联 issue -->

## 影响面
- [ ] 后端 API  - [ ] 数据入库  - [ ] 量化  - [ ] 前端  - [ ] 迁移  - [ ] 安全
- 受影响路由/页面：
- 受影响表/迁移编号：

## 口径与兼容性
- 复权口径（bfq/qfq/hfq）：
- 是否改变已有序列/回测结果：
- 破坏性变更与兼容期：

## 验证证据
- [ ] `python -m pytest bp_api/tests -q`：___ passed / ___ failed
- [ ] 定向测试：`python -m pytest ___ -q`：___ passed
- [ ] `cd web && npm test`：___ passed
- [ ] `cd web && npm run typecheck`：exit ___
- [ ] `cd web && npm run build`：exit ___
- [ ] 迁移连续执行 3 次：exit ___ / ___ / ___
- [ ] 回滚脚本演练：通过/失败
- [ ] NAV 对比：`max|Δ| = ___`（复权类必填）
- [ ] `EXPLAIN (ANALYZE, BUFFERS)`：命中索引/耗时 ___
- [ ] Bundle：目标路由 First Load JS 增量 ___ KB
- [ ] 截图：390 / 768 / 1024 / 1440（UI 类必填）
- [ ] axe：critical ___ / serious ___

## 数据与迁移
- 迁移脚本：
- schema.sql 是否同步：
- 回填策略与影响行数：
- 回滚方式：

## 风险与监控
- 主要风险：
- 监控指标/告警：
- 发布窗口与回滚触发条件：

## Reviewer Checklist
- [ ] 请求路径无计算  - [ ] 无未来函数  - [ ] NaN/Inf 已清洗
- [ ] adjust 显式过滤  - [ ] 缓存失效链完整  - [ ] revalidateTag profile 一致
- [ ] COUNT 分级未破坏  - [ ] SQL 参数化  - [ ] 越权/密钥/日志已检查
- [ ] 迁移只增不改、幂等、可回滚  - [ ] 测试与证据齐全
```
