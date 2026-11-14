# 指数估值系统 · 总体方案 v1（PRD + 技术方案 + 排期）

> 版本：2026-11-14 ｜ 状态：待 Round 4 确认 ｜ 上游决策见 `02-decisions-log.md`
> 原型：`docs/prototypes/app/index2.html`（居中 + 移动端适配版）

## 0. 一页摘要

| 项 | 内容 |
|---|---|
| 目标 | 把「指数估值」做成产品的第三个数据看板（继 CFFEX、Crypto 之后），并与组合回测打通 |
| 范围 | 521 只指数估值 PiT 库 + 估值页面族 + 股票三复权 + 篮子风险平价 + 对外 API + 加密合约看板 |
| 不做 | 不做交易执行、不做社区/订阅、不做 etf.run 的网格策略与 AI Studio |
| 数据 | 平安（一等源，覆盖最广）+ 中证官网（官方口径校验）+ 东财/乐咕/akshare（行情与补充）+ Binance（合约） |
| 交付节奏 | 6 期，每期独立可验收，预计 11~13 周（含缓冲） |
| 首个可用版本 | P0：估值数据底座 + 首页 + 详情页（约 2.5 周） |

## 1. 产品定位与边界

**一句话**：给「资产配置 / 风险平价」的使用者一个**可解释、可回溯、可编程**的指数估值工作台。

| 维度 | 决定 |
|---|---|
| 用户 | 本人（研究/配置决策）+ 公开只读访客（学习分享） |
| 频率 | 日频（T 日 21:00 落库），非实时 |
| 核心动作 | 看估值分位 → 挑资产 → 加进组合 → 回测 → 导出/调 API |
| 只读 vs 可写 | 页面只读；收藏/自选需登录且挂账户；API 需管理员签发的 token |
| 与现有模块关系 | 复用行情/交易日历/缓存/设计系统；新增独立「估值域」不污染 `bp_index_config` |

## 2. 信息架构（路由）

```
/valuation                     估值首页（卡片式：全市场 4 卡 + 宽基表 + 全部指数表）
/valuation/[code]              详情：D1（桌面默认）/ D2（<768px）/ D3（专业模式）
/valuation/compare             多指数对比（P3）
/crypto/futures                合约总览（659 合约表 + 4 KPI）
/crypto/futures/[symbol]       合约详情（左列表 + 右微观面板）
/builder                       组合构建（新增「篮子模式」Tab）
/admin/assets                  资产池（股票三复权）
/admin/api-tokens              Token 管理（超管）
/docs/api                      接入中心（公开只读）
```

导航顺序：`指数估值 / 回测 / 构建 / 加密 / 方法论`（估值插在回测之前，因为它是选资产的第一步）。

## 3. 口径体系（本方案最关键的一章）

### 3.1 实测的源差异（同一指数 930641、2026-11-11~13）

| 源 | 字段 | 数值 | 可否拿到历史 | 覆盖 |
|---|---|---|---|---|
| 平安 | `peRatio` | 23.27 | 5 年周频（peBar） | 521 指数 / 457 有 PE |
| 中证官网 | 市盈率1 / 市盈率2 | 19.55 / 19.67 | 仅滚动 20 交易日（可日积月累） | 中证系指数 |
| etf.run（参考） | 等权 PE | 29.75 | 5 年 | 351 指数 |
| 乐咕 | 滚动 PE / 中位数 | **不支持该指数**（KeyError） | 月频 2007→ | 仅约 10 个主流指数 |

**结论**：口径差异可达 **30%+**（加权 vs 等权、整体法 vs 中位数、静态 vs 滚动、是否剔除亏损股）。
因此系统必须做到：**口径字段化、多源并存、默认口径明确、差异可告警**，而不是「选一个源覆盖掉」。

### 3.2 字段化口径（DB 里标识，前端不展示 — 按 D12）

```sql
pe_basis   TEXT  -- equal_weight_ttm | cap_weight_ttm | official_pe1 | official_pe2 | vendor_default
pb_basis   TEXT  -- equal_weight | cap_weight | official
div_basis  TEXT  -- ttm | lyr
calc_src   TEXT  -- pingan | csindex | legu | eastmoney | self
is_primary BOOL  -- 同一指标同一天只有一个主口径行
```

### 3.3 源优先级（按「完整度 × 时效性」排序）

| 指标 | 主源（P0） | 校验源 | 补历史 |
|---|---|---|---|
| PE / PB / 股息率（日频、521 指数） | 平安 `INDEX_DATA` / `INDEX_DATA_V2` | 中证官网（官方口径，逐日积累） | 平安 peBar/pbBar/didHis（5 年周频） |
| 十年期国债收益率 | akshare `bond_zh_us_rate`（2015→今，日频） | 平安 `BOND10_TREND` | 已完整 |
| 指数行情（OHLCV） | 现有 `cn_index_em` | 平安 K 线 | 现有 |
| 成分股 / 权重 / 行业 | 平安 `stockList`（前 30） | 中证官网月度成分文件 | 自建月度快照 |
| 跟踪基金（规模/公司/收益） | 平安 `queryOnsiteFundInfoList` | 东财 ETF 快照 | 自建日快照 |
| ETF 净申购 / 份额 | 交易所申赎清单（待验） | 东财 | 自建日快照 |
| 全市场 PE/PB（4 张卡） | **自建归档**（每日全 A 快照） | 申万行业估值快照 | 需 3~6 个月积累 |

### 3.4 冲突与缺失处理

1. **多源并存**：同一 `(index_code, trade_date, metric)` 允许多行，靠 `calc_src` 区分；`is_primary` 唯一。
2. **差异告警**：主源与校验源同日相对差 > 20% 时写 `bp_data_quality_log`，前端详情页显示「口径提示」角标（不显示来源名）。
3. **缺失即缺失**：`NULL` 不填 0；分位计算时剔除缺失日并在 `meta.sample_size` 返回。
4. **样本量门槛**：分位窗口内有效样本 < 120 个交易日则不输出分位（返回 `null` + `reason: insufficient_sample`）。

### 3.5 分位算法（统一实现，唯一入口 `quant/valuation.py`）

```
percentile(x) = (count(历史值 <= x) - 0.5 * count(历史值 == x)) / N
窗口：5y（默认）/ 10y / 全历史；周频序列先按交易日对齐再计算
输出：pct, mean, sd, p20/p50/p80, min, max, sample_size, window
```

风险溢价 `erp = dividend_yield - bond10y`；两者必须**同日**，缺失则 `erp=NULL`。

## 4. 数据模型（新增 12 张 / 修改 3 张）

| 表 | 主键 | 关键列 | 说明 |
|---|---|---|---|
| `bp_index_valuation_daily` | (index_code, trade_date, calc_src) | pe, pe_basis, pb, pb_basis, div_ttm, div_basis, erp, bond10y, level | 日频宽表 |
| `bp_index_valuation_series` | (index_code, trade_date, metric, calc_src) | value | 长表：PE/PB/股息率历史（周频回填也进这里） |
| `bp_index_percentile` | (index_code, as_of, metric, window, calc_src) | pct, mean, sd, p20, p50, p80, sample_size | 预计算分位 |
| `bp_index_profile` | (index_code) | name, type, publisher, base_date, base_point, income_method, weight_method, intro | 静态画像 |
| `bp_index_constituent` | (index_code, effective_date, stock_code) | weight, industry_l1 | 月度快照，PiT |
| `bp_index_industry_weight` | (index_code, effective_date, industry_l1) | weight | 行业权重 |
| `bp_index_tracker_fund` | (index_code, fund_code, trade_date) | name, company, aum, nav, premium, shares | 跟踪基金日快照 |
| `bp_market_valuation_daily` | (board, trade_date) | pe, pb, pe_pct, pb_pct, sample_size | 全市场/主板/创业板/科创板 |
| `bp_stock_quote_daily` | (stock_code, adjust, trade_date) | ohlcv, pct_change | 股票三复权（或复用 quote 表 + adjust） |
| `bp_api_token` | (token_id) | name, prefix, hash, scopes, expires_at, revoked_at, last_used_at | 对外 API |
| `bp_crypto_futures_*` | 见 binance 调研 | 8 张表 | 合约数据 |
| `bp_basket_portfolio_*` | 复用 portfolio 表 | mode, method | 篮子模式 |

修改：`bp_index_quote_daily` / `bp_quote_clean` 加 `adjust`；`bp_portfolio_asset` 加 `adjust`（见 `04-quote-adjust-migration.md`）。

## 5. 采集与调度

| 时点 | 任务 | 说明 |
|---|---|---|
| 15:30 | 行情增量 | 现有 ingest |
| 18:30 | 中证官网估值文件 | 滚动 20 日，日积月累 |
| **21:00** | **平安估值全量** | 约 20 次请求；失败重试 3 次 |
| 21:20 | 国债收益率 + 全 A 快照 | 计算 ERP 与全市场估值 |
| 21:40 | 分位重算 | 只重算「主源数据有变化」的指数 |
| 22:00 | 缓存失效 | Redis + Next `revalidateTag("valuation")` |
| 每 5 分钟 | 加密合约（Tier A 30 合约） | Cloudflare Worker 抓取 → POST 回传 |
| 每小时 | 加密合约其余合约 | 同上 |

**容错**：每步写 `bp_data_refresh_run`；断点续跑；失败不阻塞下游（分位重算跳过失败标的）。

## 6. API 设计（/api/v1）

| 端点 | 关键参数 | 返回 |
|---|---|---|
| `GET /market/daily` | codes, start, end, adjust | OHLCV + pct |
| `GET /index/valuation` | codes, start, end, fields, window | 序列 + 区间统计 |
| `GET /index/percentile` | codes, metrics, windows | 分位/均值/±1,2,3σ |
| `GET /index/detail` | code | 画像 + 成分 + 跟踪基金 |
| `GET /market/bond-yield` | start, end | 10Y 国债 |
| `GET /crypto/futures` | symbols, metrics, window | 合约微观 + 分位 |

- 鉴权：`Authorization: Bearer bp_xxx`（SHA-256 存储）+ 可选 HMAC；scopes: `quotes`, `valuation`, `percentile`, `crypto`。
- 限频：默认 60 req/min，burst 10；超限 429 + `Retry-After`。
- CSV：`?format=csv` 或 `Accept: text/csv`。
- 版本策略：`/v1` 冻结字段语义，只增不改；破坏性变更开 `/v2` 并行 6 个月。

## 7. 前端设计

- **布局**：全站 `max-width: 1240px` 居中；顶部固定导航；内容区 24px 内边距。
- **响应式**：≥1100 三栏/双栏；768~1100 双栏收窄；<768 单栏（卡片 1 列、表格横向滚动、D3 专业模式隐藏）。
- **性能**：页面 SSR + `cacheLife("hours")` + `cacheTag("valuation")`；图表按需 `dynamic(() => import(...), {ssr:false})`；表格 >300 行启用虚拟滚动。
- **新增组件（约 18 个）**：`ValuationCover`、`MarketValuationCards`、`IndexTable`、`PercentileBar`、`DualAxisChart`、`ConstituentBars`、`IndustryBars`、`GrowthChart`、`DrawdownLevels`、`EtfFlowChart`、`EtfFlowTable`、`AdjustSegmented`、`BasketGroupCard`、`BasketWeightTable`、`RiskContributionBars`、`FuturesKpi`、`MicrostructureTable`、`ApiCodeBlock`。
- **一致性**：图表颜色只走 `chart-theme.ts`；涨跌色支持用户偏好（默认绿涨红跌）；危险操作 AlertDialog；反馈 sonner。

## 8. 分期路线图

| 期 | 范围 | 交付物 | 工期 | 验收 |
|---|---|---|---|---|
| **P0** | 行情 adjust 维度、估值表、平安采集、债券收益率、分位计算、首页+详情 D1/D2、缓存链 | 约 12 个新文件 + 3 张表 | 2.5 周 | 迁移后回测 NAV 零漂移；521 指数日更成功；详情页 TTFB < 400ms |
| **P1** | 中证官网源 + 多源口径 + 差异告警 + 成分/跟踪基金 + 成分与业绩 Tab + ETF 资金 Tab | 4 张表 | 2 周 | 多源同日差异可查；成分权重与官方一致率 > 98% |
| **P2** | 对外 API + token 管理 + Python SDK + Excel Power Query 模板 + /docs/api | 1 张表 | 2 周 | Excel 一次拉 5 万行 < 10s；鉴权/限频/错误码全覆盖 |
| **P3** | 股票全 A 三复权（含回退策略）+ 构建器 UI | 复用 quote 表 | 2 周 | 1800 只 × 3 口径日更 < 30min；UI 口径切换无感 |
| **P4** | 篮子风险平价（6 方法）+ 前端篮子模式 | 复用 portfolio | 1.5 周 | 6 方法结果可复现；权重合计与约束校验通过 |
| **P5** | 加密合约看板（Tier A 30 合约 5min + 全量日频）+ 总览/详情页 + Cloudflare Worker | 8 张表 | 2 周 | 5min 桶延迟 < 90s；分位 5 窗口可用 |
| **P6** | 全市场估值（自建归档满 3 个月后切真值）+ 对比页 + 打磨 | — | 1 周 | 全市场分位可用；Lighthouse ≥ 90 |

## 9. 验收标准（量化）

| 类别 | 指标 |
|---|---|
| 数据 | 521 指数日更成功率 ≥ 99%；单指数连续缺失 ≤ 2 日；多源同日差异 > 20% 全部告警 |
| 正确性 | 迁移前后回测 NAV `max|Δ| < 1e-12`；分位与手算一致（3 个固定样本） |
| 性能 | 首页 TTFB < 400ms（缓存命中）；详情页 < 500ms；表格 500 行滚动 60fps |
| API | P99 < 300ms；错误码全覆盖；限频正确返回 429 |
| 前端 | 断点 390/768/1024/1440 无横向溢出；键盘可达；对比度 AA |
| 工程 | `pytest` 全绿；`npm run build`/`typecheck` 通过；新增测试覆盖率关键路径 100% |

## 10. 风险登记册

| 风险 | 影响 | 缓解 |
|---|---|---|
| 平安接口变更/封禁 | 主源断供 | 中证官网 + 东财双备；数据断档不填 0；告警 |
| 东财限频 | 股票全 A 抓取失败 | 回退 1800 → 50；夜间分批；curl-cffi 硬化 |
| TimescaleDB 加列重写 | 停机窗口 | 低峰执行 + pg_dump + 分阶段（写后读） |
| 全 A 股口径不一致 | 分位偏差 | 只做自建归档，标注 as-of；3 个月后再切 |
| 跨境 Binance 不稳定 | 合约数据缺口 | Worker 重试 + DLQ + 缺口标记（不补假值） |
| 口径争议 | 用户误读 | meta 返回 basis/calc_src；文档明示 |

## 11. Round 4 待决策

见对话中的 Q27~Q32。