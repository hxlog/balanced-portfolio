# 指数估值系统 · 验收与测试计划

> 版本：2026-11-14 ｜ 适用：P0~P6 全部交付 ｜ 上游：`05-master-plan.md`、`04-quote-adjust-migration.md`、`06-data-model-v3.md`
> 基线：后端 `pytest` 当前收集 **266** 个用例（CI 口径 Python 3.11）；前端 vitest 当前 **6** 个文件；CI 见 `.github/workflows/ci.yml`。
> 原则：每条验收必须是「可执行命令 + 可判定输出」；禁止用「页面正常」「数据正确」这类主观描述。

## 1. 验收分层与量化指标

| 层级 | 验收对象 | 指标 | 阈值 | 证据 |
|---|---|---|---|---|
| 数据层 | 521 只跟踪指数日更 | 当日主口径覆盖率 | ≥ 99.00%（≥ 516/521） | 覆盖率 SQL + `bp_data_refresh_run` |
| 数据层 | 单指数连续性 | 连续缺失交易日 | ≤ 2 日；>2 日必须告警 | 连续缺失 SQL |
| 数据层 | 多源一致性 | 同日相对差 >20% 的告警漏报 | 0 条 | `bp_data_quality_log` 对账 SQL |
| 数据层 | 主口径唯一性 | `(index_code,trade_date)` 多条 `is_primary` | 0 组 | 唯一性 SQL |
| 数据层 | PiT 语义 | `captured_at < trade_date` 的行 | 0 条 | PiT SQL |
| 数据层 | 复权迁移 | 迁移前后 NAV `max|Δ|` | < 1e-12 | 对比脚本 |
| API 层 | `/api/v1/*` | P99 延迟（50 VU / 30s） | < 300 ms | k6 或 autocannon |
| API 层 | 鉴权与限频 | 401/403/429 分支覆盖 | 100% | `test_api_v1.py` |
| API 层 | 导出 | 5 万行 CSV 端到端 | < 10 s | `curl -w` + 行数校验 |
| 前端层 | 首页 TTFB | 缓存命中 P95 | < 400 ms | `curl -w` ×10 |
| 前端层 | 详情页 TTFB | 缓存命中 P95 | < 500 ms | `curl -w` ×10 |
| 前端层 | 断点 | 390/768/1024/1440 横向溢出 | 0 px | Playwright 断言 |
| 前端层 | 可访问性 | axe critical/serious | 0；正文对比度 ≥ 4.5:1 | `@axe-core/playwright` |
| 前端层 | 表格 | 500 行滚动帧率 | ≥ 55 fps，长任务 < 50 ms | Playwright + rAF |
| 前端层 | 性能评分 | Lighthouse Performance（P6） | ≥ 90 | Lighthouse JSON |
| 工程层 | 后端 | 全量 pytest | 0 failed；P6 后 ≥ 428 passed | CI 日志 |
| 工程层 | 前端 | test / typecheck / build | 全部 exit 0 | CI 日志 |
| 工程层 | 迁移 | 同一脚本连续执行 3 次 | 每次 exit 0，行数不变 | 临时库日志 |
| 工程层 | 安全 | 明文 token / 密钥入 git | 0 条 | gitleaks + `git grep` |

### 1.1 数据完整性 SQL（P0 起每期必跑；落为 `scripts/sql/val_*.sql`）

```sql
-- ① 521 日更覆盖率：期望 pct>=99.00（covered>=516）
SELECT count(*) tracked, count(v.index_code) covered,
       round(100.0*count(v.index_code)/count(*),2) pct
FROM bp_index_master m LEFT JOIN bp_index_valuation_daily v
  ON v.index_code=m.index_code AND v.trade_date=DATE '2026-11-13' AND v.is_primary
WHERE m.is_active AND m.is_tracked;

-- ② 连续缺失>2交易日：期望 0 行
WITH d AS (SELECT index_code, trade_date,
                  lag(trade_date) OVER (PARTITION BY index_code ORDER BY trade_date) prev
           FROM bp_index_valuation_daily WHERE is_primary),
     g AS (SELECT d.*, (SELECT count(*) FROM bp_trading_calendar c
                        WHERE c.market='CN' AND c.is_trading
                          AND c.cal_date>d.prev AND c.cal_date<d.trade_date) missing_days
           FROM d WHERE d.prev IS NOT NULL)
SELECT index_code, prev, trade_date, missing_days FROM g
WHERE missing_days>2 ORDER BY missing_days DESC;

-- ③ 多源差异>20%与告警对账：期望 missing_alerts=0
WITH d AS (SELECT p.index_code, p.trade_date,
                  abs(p.pe_ttm-c.pe_ttm)/nullif(p.pe_ttm,0) rel_diff
           FROM bp_index_valuation_daily p JOIN bp_index_valuation_daily c
             ON c.index_code=p.index_code AND c.trade_date=p.trade_date
            AND c.calc_src='csindex_value' AND c.pe_ttm IS NOT NULL
           WHERE p.calc_src='pingan_index' AND p.is_primary AND p.pe_ttm IS NOT NULL),
     a AS (SELECT index_code, trade_date FROM bp_data_quality_log
           WHERE metric='pe_ttm' AND level IN ('warn','error'))
SELECT (SELECT count(*) FROM d WHERE rel_diff>0.20) diff_rows,
       (SELECT count(*) FROM d WHERE rel_diff>0.20 AND NOT EXISTS
          (SELECT 1 FROM a WHERE a.index_code=d.index_code AND a.trade_date=d.trade_date)) missing_alerts;
```

## 2. 分期验收清单（P0~P6）

### P0 数据底座 + 首页/详情 + 复权维度

| # | 命令 | 期望输出 |
|---|---|---|
| 1 | `python -m pytest bp_api/tests/test_quote_adjust.py bp_api/tests/test_valuation.py bp_api/tests/test_valuation_ingest.py bp_api/tests/test_valuation_api.py -q` | `56 passed`（14+20+12+10） |
| 2 | `python scripts/compare_nav_adjust_migration.py --portfolios demo --tol 1e-12` | `max|ΔNAV|=0.000000e+00 < 1e-12`，exit 0（新增脚本） |
| 3 | `python -m bp_ingest valuation --date 2026-11-13 --verify` | `tracked=521 covered>=516 pct>=99.00`（新增 CLI） |
| 4 | `psql -f scripts/sql/val_primary_unique.sql` | `duplicate_groups=0` |
| 5 | `psql -f scripts/sql/val_missing_streak.sql` | `0 rows`（不存在连续缺失 >2 日的指数） |
| 6 | `psql -f scripts/sql/val_pit_violation.sql` | `violations=0` |
| 7 | `for i in $(seq 1 10); do curl -s -o /dev/null -w "%{time_starttransfer}\n" https://HOST/valuation; done` | P95 < `0.400` |
| 8 | `for i in $(seq 1 10); do curl -s -o /dev/null -w "%{time_starttransfer}\n" https://HOST/valuation/000300; done` | P95 < `0.500` |
| 9 | `curl -X POST https://HOST/api/revalidate/valuation -H "X-Internal-Token: $BP_INTERNAL_REVALIDATE_TOKEN"` | HTTP 200，`{"revalidated":true,"tag":"valuation"}` |
| 10 | `python -m pytest bp_api/tests -q` | `>= 322 passed, 0 failed` |
| 11 | `cd web && npm test && npm run typecheck && npm run build` | 三条命令均 exit 0 |
### P1 中证官网源 + 多源口径 + 成分/跟踪基金

| # | 命令 | 期望输出 |
|---|---|---|
| 1 | `python -m pytest bp_api/tests/test_valuation_sources.py -q` | `16 passed` |
| 2 | `psql -f scripts/sql/val_source_diff_alert.sql` | `missing_alerts=0`；`diff_rows=alert_rows` |
| 3 | `python scripts/verify_constituent_weights.py --index 000300 --date 2026-10-31` | `match_rate>=98.00%` |
| 4 | `psql -c "SELECT count(*) rows, round(100.0*count(aum)/nullif(count(*),0),2) aum_pct FROM bp_index_tracker_fund WHERE trade_date=DATE '2026-11-13'"` | `rows>0`；`aum_pct>=95.00` |
| 5 | `npx playwright test web/e2e/valuation-detail.spec.ts -g "口径提示"` | 角标可见；来源名不可见 |
| 6 | `python -m pytest bp_api/tests -q` | `>= 338 passed, 0 failed` |
### P2 对外 API + Token + SDK/Power Query

| # | 命令 | 期望输出 |
|---|---|---|
| 1 | `python -m pytest bp_api/tests/test_api_v1.py -q` | `22 passed` |
| 2 | `npx autocannon -c 50 -d 30 -p 10 -H "Authorization=Bearer $TOKEN" "http://127.0.0.1:8000/api/v1/index/percentile?codes=000300&metrics=pe_ttm&windows=5y"` | `99th percentile < 300 ms`，`non-2xx=0` |
| 3 | `python scripts/verify_rate_limit.py --token $TOKEN --requests 61 --window 60` | 第 61 次起 HTTP 429，带 `Retry-After`（新增脚本） |
| 4 | `time curl -o /tmp/export.csv ".../api/v1/index/valuation?format=csv&start=2015-01-01"` | `real < 10s`；`wc -l /tmp/export.csv` 与 `rows` 一致且 ≥50000 |
| 5 | `psql -c "SELECT count(*) FROM bp_api_token WHERE token_hash !~ '^[0-9a-f]{64}$'"` | `0`；表结构无明文 token 列 |
### P3 全 A 股三复权 + 构建器 UI

| # | 命令 | 期望输出 |
|---|---|---|
| 1 | `python -m pytest bp_api/tests/test_stock_adjust.py -q` | `16 passed` |
| 2 | `time python -m bp_ingest stocks --all --adjust bfq qfq hfq --date 2026-11-13` | `real < 30min`；`failed_symbols=0`；`rows=5400`（1800×3） |
| 3 | `psql -c "SELECT count(DISTINCT adjust) FROM bp_quote_clean WHERE symbol='600036' AND source='stock_em'"` | `3` |
| 4 | `python -m pytest bp_api/tests/test_backtest.py bp_api/tests/test_coverage.py -q` | `27 passed` |
| 5 | `npx playwright test web/e2e/admin-adjust.spec.ts -g "三口径切换"` | 3 次请求均 200；图表/区间文案随口径变化；控制台 0 error |
### P4 篮子风险平价（6 方法）

| # | 命令 | 期望输出 |
|---|---|---|
| 1 | `python -m pytest bp_api/tests/test_basket.py -q` | `18 passed` |
| 2 | `python scripts/verify_basket_methods.py --portfolio-id <id> --runs 2` | 6 方法均 `max|Δw|<1e-12`；`|Σw-1|<1e-8` |
| 3 | `python -m pytest bp_api/tests/test_basket.py -q -k risk_budget_invalid` | `2 passed`；返回 422，错误码 `invalid_risk_budget` |
| 4 | `python scripts/verify_basket_nav_parity.py --portfolio-id <id> --tol 1e-12` | `max|Δ|=0.000000e+00`（新增脚本） |
### P5 加密合约看板
| # | 命令 | 期望输出 |
|---|---|---|
| 1 | `python -m pytest bp_api/tests/test_crypto_futures.py -q` | `22 passed` |
| 2 | `psql -f scripts/sql/futures_freshness.sql` | Tier A 30 合约 `max(now()-observed_at) < 90s`（P95） |
| 3 | `psql -c "SELECT count(DISTINCT symbol) FROM bp_crypto_futures_kline_5m WHERE open_time::date=CURRENT_DATE"` | ≥ 659×99% |
| 4 | `psql -f scripts/sql/futures_oi_nulls.sql` | `zero_rows=0`（缺失存 NULL，未填 0） |
| 5 | `psql -c "SELECT count(DISTINCT window_key) FROM bp_crypto_futures_percentile WHERE as_of_date=CURRENT_DATE"` | `5`（1h/4h/1d/7d/30d） |
| 6 | `python scripts/verify_internal_ingest_idempotency.py --nonce test-001 --repeat 2` | `rows_delta=0`；第二次 HTTP 200（新增脚本） |
### P6 全市场估值 + 对比页 + 打磨
| # | 命令 | 期望输出 |
|---|---|---|
| 1 | `python -m pytest bp_api/tests/test_market_valuation.py -q` | `12 passed` |
| 2 | `psql -c "SELECT count(DISTINCT board) FROM bp_market_valuation_daily WHERE trade_date=(SELECT max(trade_date) FROM bp_market_valuation_daily)"` | `5`（all/main/chinext/star/bse） |
| 3 | `psql -c "SELECT count(DISTINCT trade_date) FROM bp_market_valuation_daily WHERE board='all'"` | ≥ 60 个交易日；不足则分位返回 `insufficient_history`，禁止伪造 |
| 4 | `npx lighthouse http://localhost:3000/valuation --only-categories=performance --chrome-flags="--headless" --output=json` | `categories.performance.score >= 0.90` |
| 5 | `npx playwright test web/e2e/valuation-compare.spec.ts` | 全部 passed |
## 3. 测试金字塔：新增文件与关键用例

| 层 | 新增文件 | 关键用例（中文） | 一句断言 |
|---|---|---|---|
| 单元 | `test_quote_adjust.py` | 同一股票三口径并存且互不覆盖 | `count(DISTINCT adjust)=3` 且各序列收盘价独立 |
| 单元 | 同上 | 存量 ETF 迁移后被打标为 `hfq` | `source IN ('etf_em','etf_tx')` 的行 `adjust='hfq'` |
| 单元 | 同上 | `row_hash` 与主键均包含 `adjust` | 同 symbol+date 三口径 `row_hash` 两两不等 |
| 单元 | 同上 | 回测按组合资产声明的 `adjust` 取数 | 改 `adjust` 后权重/NAV 变化，且不读其他口径 |
| 单元 | `test_valuation.py` | 分位公式含重复值中点修正 | `(count(<=x)-0.5*count(==x))/N` 与手算差 <1e-12 |
| 单元 | 同上 | 有效样本 <120 返回 `insufficient_sample` | `pct is None` 且 `sample_size<120` |
| 单元 | 同上 | 缺失值不填 0 | 输入含 `NULL` 时 `sample_size` 只计有效值 |
| 单元 | 同上 | ERP 必须同日 | 任一侧缺失时 `erp is None` |
| 单元 | `test_valuation_ingest.py` | 平安 `peBar/pbBar/didHis` 解析 | 260 点周频完整解析，坏点跳过不写脏行 |
| 单元 | 同上 | 抓取失败重试 3 次且不落半行 | 失败后该指数当日 0 行，`refresh_run` 记 error |
| 单元 | `test_valuation_sources.py` | 主源/校验源相对差 >20% 写质量日志 | `rel_diff>0.2` 时 `bp_data_quality_log` 恰 1 行 |
| 单元 | `test_stock_adjust.py` | 全 A 三口径抓取失败不覆盖成功口径 | 单口径失败时其余两口径行数不变 |
| 单元 | `test_basket.py` | 6 方法权重和与约束 | 每种方法 `|Σw-1|<1e-8`，负权重被拒 |
| 单元 | `test_crypto_futures.py` | OI/多空比缺失不补 0 | 缺失日落库 `NULL`，分位样本剔除 |
| 单元（前端） | `web/lib/valuation-format.test.ts` | 小数分位转百分比 | `0.1234 -> "12.34%"`；`null -> "—"` |
| 单元（前端） | `web/lib/valuation-percentile.test.ts` | ±σ / p20/p50/p80 格式化 | 空值不渲染 `NaN`，负号正确 |
| 单元（前端） | `web/lib/basket-calc.test.ts` | 6 方法标签与权重校验 | 未知方法回退默认而非崩溃 |
| 单元（前端） | `web/lib/adjust-label.test.ts` | 类别 × 复权标签 | 股票默认 `hfq`，指数默认 `bfq` |
| 集成 | `test_pipeline_valuation.py` | 抓取→落库→分位→API 全链路 | 同一 as_of 的 API 值等于预计算表值 |
| 集成 | `test_migration_51_56.py` | 临时库连续执行迁移 3 次 | 每次 exit 0；表/约束/索引与 schema.sql 一致 |
| 集成 | `test_api_contract_v1.py` | OpenAPI 契约与错误码 | 401/403/404/422/429/500 全部有快照 |
| 端到端 | `web/e2e/valuation-home.spec.ts` | 4 断点 + 4 张卡 + 表格 | 无横向溢出；卡片列数 1/2/2/4 |
| 端到端 | `web/e2e/valuation-detail.spec.ts` | 3 Tab + 图表 + 空/错/载 | 每个 Tab 可键盘切换；空态文案可见 |
| 端到端 | `web/e2e/builder-basket.spec.ts` | 篮子模式 6 方法 | 切换方法后权重表与风险贡献刷新 |
| 端到端 | `web/e2e/admin-adjust.spec.ts` | 股票复权选项与新建 | 三口径资产创建成功且列表徽章正确 |
| 端到端 | `web/e2e/crypto-futures.spec.ts` | 合约总览/详情 | 659 合约表可筛选；KPI 非空 |
> 目标配比：单元 ≥70%（≥300 用例）、集成 ≥20%（≥60 用例）、E2E ≥10%（≥25 场景）。新增关键路径覆盖率要求 100%，非关键路径不低于现有水平。
## 4. 数据正确性「金标准」：3 个固定样本

固定样本：`930641`（平安周频主源）、`000300`（宽基/中证官方口径）、`H30374`（中证策略指数，原码不补零）。每个样本冻结 CSV 与期望 JSON：`bp_api/tests/fixtures/valuation_golden/{code}.csv`、`{code}.expected.json`；CI 禁止 `--update-golden`。

| 步骤 | 操作 | 可复现命令/公式 |
|---|---|---|
| 1 | 冻结口径 | `as_of=2026-11-13`；`metric=pe_ttm`；`window=5y`（`trade_date > as_of - interval '5 years'`）；`calc_src` 随样本固定 |
| 2 | 导出原始序列 | `psql -c "\copy (SELECT trade_date,value FROM bp_index_valuation_series WHERE index_code='930641' AND metric='pe_ttm' AND calc_src='pingan_index' AND trade_date > DATE '2026-11-13' - INTERVAL '5 years' AND trade_date <= DATE '2026-11-13' ORDER BY trade_date) TO '930641.csv' CSV HEADER"` |
| 3 | 取当前值 x | `x = 最新 trade_date 的 value`（930641 实测样例 PE=23.27） |
| 4 | 手算分位 | `N=有效样本数`；`pct=(COUNTIF(range,"<="&x)-0.5*COUNTIF(range,x))/N`；结果存 0~1 小数，展示层 ×100 |
| 5 | 手算均值/标准差 | `mean=AVERAGE(range)`；`sd=STDEV.S(range)`（样本标准差，N<2 时 `null`）；`±kσ = mean ± k*sd`，k=1,2,3 |
| 6 | 手算分位点 | `p20/p50/p80=PERCENTILE.INC(range,0.2/0.5/0.8)`；与 `numpy.percentile(..., method='linear')` 对齐 |
| 7 | 与系统对比 | 逐字段 `abs(system-manual)`：`pct/mean/sd < 1e-9`；`p20/p50/p80 < 1e-6`；`sample_size` 完全相等 |

对 `000300`/`H30374` 将第 2 步的 `index_code` 与 `calc_src` 替换为对应值后重复步骤 2~7。三个样本各自锁定：`930641` 验证周频回填与主源；`000300` 验证官方 `official_pe1/official_pe2` 多源并存；`H30374` 验证原码主键、样本量边界与 `insufficient_sample`。对应测试：`test_golden_930641_pct_matches_manual`、`test_golden_000300_mean_sd_matches_manual`、`test_golden_h30374_percentile_points_match_manual`。期望值在 P0 冻结日由两人独立手算后签字写入，禁止用系统输出回填。

## 5. 前端验收：断点、键盘、对比度、图表、状态

| 维度 | 检查点 | 通过标准 | 工具/命令 |
|---|---|---|---|
| 断点 390 | 卡片 1 列、表格横向滚动、D3 专业模式隐藏、导航抽屉 | `document.documentElement.scrollWidth <= window.innerWidth+1`；点击目标 ≥44px | Playwright `viewport:{width:390,height:844}` |
| 断点 768 | 2 列、D2 布局、表格容器可滚 | 同上；无元素重叠 | Playwright |
| 断点 1024 | 2~3 列、D1 桌面布局 | 同上；侧栏不挤压主图 | Playwright |
| 断点 1440 | 内容 `max-width:1240px` 居中、4 卡 | 左右留白对称；无横向溢出 | Playwright |
| 键盘 | Tab 顺序、Enter/Space、Tab 组件方向键、Esc 关闭弹窗 | 全程可见焦点环；无键盘陷阱 | Playwright `keyboard.press` |
| 对比度 | 正文、按钮、图表轴标签 | 正文 ≥4.5:1；大字 ≥3:1；axe 0 critical/serious | `@axe-core/playwright` |
| 图表 | ECharts 渲染、resize、tooltip、空数据 | canvas 非空；resize 后不模糊；空数据有文案 | Playwright + `aria` 配置 |
| 空态 | 无估值/无成分/无跟踪基金 | 显示「暂无估值数据」，不显示 `null/NaN` | E2E 断言 |
| 错误态 | API 500/超时 | 显示重试按钮；重试后恢复 | 拦截路由 mock 500 |
| 加载态 | 首屏/切换 Tab | 骨架屏无布局抖动（CLS <0.1） | Lighthouse / PerformanceObserver |
| 涨跌色 | `text-up/text-down` | 仅方向性涨跌使用；范围提示用 `destructive/warning` | 代码审查 + 视觉回归 |

命令：`npx playwright test web/e2e/valuation-*.spec.ts --project=chromium`；`npx playwright test web/e2e/a11y.spec.ts`。视觉回归基线存 `web/e2e/__screenshots__/`，4 个断点各 1 张。

## 6. 性能测试

| 指标 | 方法 | 命令 | 阈值 |
|---|---|---|---|
| 首页 TTFB | 缓存预热后 10 次取 P95 | `for i in $(seq 1 10); do curl -s -o /dev/null -w "%{time_starttransfer}\n" https://HOST/valuation; done` | < 0.400 s |
| 详情页 TTFB | 同上，`/valuation/000300` | 同上 | < 0.500 s |
| API P99 | k6 50 VU / 30 s | `k6 run -e BASE=http://127.0.0.1:8000 -e TOKEN=$TOKEN perf/percentile.js` | `http_req_duration p(99)<300`；`http_req_failed<0.1%` |
| API 备选 | autocannon | `npx autocannon -c 50 -d 30 -p 10 -H "Authorization=Bearer $TOKEN" "http://127.0.0.1:8000/api/v1/index/percentile?codes=000300&metrics=pe_ttm&windows=5y"` | 99th < 300 ms；non-2xx 0 |
| 表格 500 行 | rAF 测帧 + 滚动 2 s | Playwright：`requestAnimationFrame` 计数 / 2 | ≥55 fps；长任务 <50 ms |
| Lighthouse | P6 首页/详情 | `npx lighthouse https://HOST/valuation --only-categories=performance --chrome-flags="--headless" --output=json` | score ≥0.90 |
| 数据库 | 慢查询计划 | `EXPLAIN (ANALYZE, BUFFERS) <SQL>` | 走索引/分区裁剪；执行 <50 ms；大表无 Seq Scan |
| 缓存 | Redis/Next 命中 | `curl -sI https://HOST/valuation` + 应用指标 | 缓存命中率 ≥90% |

k6 脚本 `perf/percentile.js` 固定 50 VU/30s，阈值 `http_req_duration p(99)<300`、`http_req_failed<0.1%`。500 行表格测量：在 E2E 中执行 `await page.evaluate(() => new Promise(res => { let n=0; const t0=performance.now(); const f=()=>{n++; performance.now()-t0<2000?requestAnimationFrame(f):res(n/2)}; requestAnimationFrame(f); }))`，同时用 `PerformanceObserver` 断言 `longtask` 最大时长 <50 ms。

## 7. 复权维度回归清单（8 个消费点）

| # | 消费点 | 风险 | 验证命令 | 期望 |
|---|---|---|---|---|
| 1 | 回测 | 取错口径导致 NAV 漂移 | `python -m pytest bp_api/tests/test_backtest.py -q`；`python scripts/compare_nav_adjust_migration.py --tol 1e-12` | 13 passed；`max|ΔNAV|<1e-12` |
| 2 | 清洗 | 面板键未含 `adjust` 导致串行 | `python -m pytest bp_api/tests/test_fx_cleaning.py -q`；`psql -c "SELECT count(DISTINCT adjust) FROM bp_quote_clean WHERE symbol='600036'"` | 22 passed；`3` |
| 3 | coverage | 覆盖判定未按口径 | `python -m pytest bp_api/tests/test_coverage.py -q` | 14 passed；`effective_start` 与引擎逐字相等 |
| 4 | CFFEX | 误取多口径期货行 | `python -m pytest bp_api/tests/test_cffex.py -q`；`psql -f scripts/sql/cffex_dup.sql` | 23 passed；`dup=0` |
| 5 | crypto | 未显式 `bfq` 导致重复 | `python -m pytest bp_api/tests/test_crypto_corr.py -q`；重算前后 `bp_crypto_corr_daily` 行数对比 | 17 passed；行数差 0 |
| 6 | admin | 股票复权选项/新建失败 | `python -m pytest bp_api/tests/test_asset_create_flow.py -q`；手工新建三口径资产 | 26 passed；3 条资产可查 |
| 7 | API | `/market/daily` 未带 `adjust` | CI 路由冒烟；`curl ".../api/v1/market/daily?code=600036&adjust=hfq"` | 返回 1 条序列且 `adjust=hfq` |
| 8 | 前端 | 徽章/切换/默认排序错 | `cd web && npm test && npm run typecheck && npm run build`；`npx playwright test web/e2e/admin-adjust.spec.ts` | 全绿；无 5xx/控制台错误 |

补充：`python -m pytest bp_api/tests/test_source_aggregation.py -q`（13 passed）验证东财→新浪/腾讯降级不破坏 `adjust` 透传；`python -m bp_ingest clean` 后必须重跑第 2、3、8 项。

## 8. 上线准入（Go/No-Go）检查表

| # | 检查项 | 阈值 | 证据 | 阻断 |
|---|---|---|---|---|
| 1 | 复权迁移 NAV 漂移 | `max|Δ| < 1e-12` | 对比脚本输出 | 是 |
| 2 | 521 指数日更覆盖率 | ≥99.00% | 覆盖率 SQL | 是 |
| 3 | 连续缺失 | 无 >2 日；异常有告警 | 缺失 SQL + 告警截图 | 是 |
| 4 | 主口径唯一性 | 0 组重复 | 唯一性 SQL | 是 |
| 5 | 多源差异告警 | 漏报 0 | 对账 SQL | 是 |
| 6 | 全量 pytest | 0 failed，≥当期目标 | CI 日志 | 是 |
| 7 | 前端三件套 | test/typecheck/build 全 exit 0 | CI 日志 | 是 |
| 8 | API P99 / 首页与详情 TTFB | <300/400/500 ms | k6/curl 报告 | 是 |
| 9 | 迁移幂等 | 连续 3 次 exit 0，行数不变 | 临时库日志 | 是 |
| 10 | 回滚演练 | 回滚脚本执行成功，旧读路径可用 | 演练记录 | 是 |
| 11 | 备份 | 上线前 `pg_dump` 完成且可恢复 | 备份校验记录 | 是 |
| 12 | 安全 | 无明文 token/密钥；token 仅 hash | gitleaks + SQL | 是 |
| 13 | 监控告警 | 抓取失败/分位耗时/API 5xx 有通知渠道 | 告警配置截图 | 是（生产） |
| 14 | 文档与免责声明 | 数据来源、口径、免责声明、sitemap/OG 已上线 | URL + 截图 + `curl` 200 | 否 |

**Go 条件**：1~13 全部通过；任一阻断项失败即 No-Go 并回滚。发布后 2 小时内观察：521 覆盖率、API 5xx、P99、缓存命中率、`bp_data_quality_log` 新增条数；异常按 `deploy/OPS.md` 回滚。
