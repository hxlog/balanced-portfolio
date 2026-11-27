# 数据层第二轮整改 · cron 建议与已知限制（2026-11-27）

> 本文件只记录部署与数据口径建议，**未在生产执行**。所有时间均为北京时间（CST）。
> 冻结口径：不改视觉、不伪造历史；缺失数据以 freshness note / issue / coverage_start 明示。

## 1. cron 建议（部署时由运维加入 crontab）

```cron
# 指数行情免费源：16:00-23:00 每 15 分钟 + 09:00 兜底（覆盖 tracked 指数；WAF 免疫降级链）
*/15 16-23 * * 1-5  cd /opt/balanced-portfolio && .venv/bin/python scripts/index_quotes_free.py >> logs/index_quotes_free.log 2>&1
0    9    * * 1-5   cd /opt/balanced-portfolio && .venv/bin/python scripts/index_quotes_free.py >> logs/index_quotes_free.log 2>&1

# 指数/legacy 行情落库后的 clean 增量对账（index_quotes_free 已内置收尾，此处为二次兜底）
10   21   * * 1-5   cd /opt/balanced-portfolio && .venv/bin/python scripts/repair_quote_clean.py --apply >> logs/repair_quote_clean.log 2>&1

# legacy 旧链 raw 回填（先 dry-run 确认，再 --apply；v3 ETL/免费源优先，含 hfq）
# 建议 nightly 21:05 前置执行，随后 repair_quote_clean 收尾
5    21   * * 1-5   cd /opt/balanced-portfolio && .venv/bin/python scripts/backfill_legacy_quotes.py --apply >> logs/backfill_legacy.log 2>&1

# 市场估值快照（新浪免费源）与 10Y 国债收益率
20   21   * * 1-5   cd /opt/balanced-portfolio && .venv/bin/python -m bp_ingest.market_valuation >> logs/market_valuation.log 2>&1
40   21   * * 1-5   cd /opt/balanced-portfolio && .venv/bin/python -m bp_ingest.risk_free --days 30 >> logs/risk_free.log 2>&1
# 10Y 历史回填：一次性执行（2017 起；源可用范围内），不要每天跑
# .venv/bin/python -m bp_ingest.risk_free --start 2017-01-01

# 估值历史回补（000985 中证全指）：首次接入/历史不足 3 年时执行一次
# .venv/bin/python scripts/index_quotes_free.py --symbols 000985 --start 2017-01-01
# .venv/bin/python -m bp_ingest.valuation_job --as-of 2026-11-27   # fallback 估值每日快照

# 每日 09:30 全站数据体检（覆盖率/时效/准确性；error 时 exit 1 触发告警）
30   9    * * 2-6   cd /opt/balanced-portfolio && .venv/bin/python scripts/daily_data_audit.py >> logs/daily_data_audit.log 2>&1
```

说明：

- 09:30 体检放在 09:00 指数行情兜底之后，确保「昨日应到」数据已尽力补齐再判定；
  周二至周六执行（周一 09:30 覆盖上周五，节假日由交易日历判定应到日）。
- 指数行情 16:00-23:00 高频轮询是为了在源限流/间歇 WAF 下多轮补缺；09:00 兜底
  覆盖夜间未完成的尾部缺口。收尾默认 upsert `bp_index_quote_health` 并对新行情
  symbol 增量 rebuild clean（`--no-postprocess` 可关）。
- 09:30 体检写 `bp_data_audit_daily`（ddl/82）与 `bp_etl_quality_issue`，
  `GET /api/v1/market/data-health` 只读最近一次结果。
- legacy 旧链 hfq 缺口根因已修：覆盖率分母按 `bp_index_config.adjust_modes` 过滤
  （hfq 分母 124 而非全 universe 287），orchestrator 使用该分母后 state 可正常推进、
  backlog 可被清空。

## 2. 已知限制（记录，不伪造）

| 数据 | 限制 | 正在做的处理 | 明确不做 |
|---|---|---|---|
| 全市场估值快照 | 历史仅 **2026-11-14 / 2026-11-27** 两日（东财 clist 封禁；新免费源自 11-26 起才可用） | freshness `market_valuation` 显示 as_of / stale，cron 21:20 每日积累 | 不插值、不回填不存在的历史；UI 不得宣称有长历史 |
| 10Y 国债收益率 | 旧调度无 owner，11-20 起停更；现走 chinabond/akshare/新浪免费源（`bp_ingest.risk_free`） | cron 21:40 + 09:30 兜底；可用 `python -m bp_ingest.risk_free --start 2017-01-01` 一次性回填（源有数据范围内） | 不伪造缺失日期、不做 forward-fill 进估值 ERP（ERP 仅同日） |
| 000985 中证全指·估值 | 免费源（中证官网 indicator.xls）**仅滚动约 20 个交易日**，`coverage_start=2026-11-02` 起；**无 PB**；PE 只有总股本/计算用股本两种口径 | 每日 21:00 估值任务落快照逐步积累；`bp_index_valuation_latest.coverage_start` 明示起点；freshness meta/issue 记录 `pb_available=false` 与口径 | 不用 PEG 反推 PE；不用其他指数/口径冒充 PB；不插值造长历史 |
| 000985 中证全指·行情 | 此前仅 34 行（有近期行情即跳过全史回补） | `fetch_csindex_fallback` full_history 改为优先中证官网 index-perf JSON（2017 起约 2400+ 行）；`need_full` 改为「行情 < 3 年」；`index_quotes_free --symbols 000985 --start 2017-01-01` 可补全 | 不把 index-perf 的收盘价反推/拼接到其他指数 |
| 指数行情覆盖 | 11-24 停旧 cron 后 tracked 指数按日 distinct 一度 675→505（11-27 手动 284/481=59%）；US/GLOBAL 指数无免费源 | 16-23 q15 + 09:00 轮询；930/931/932/H3/950 走 index-perf JSON → OSS perf.xls → 东财降级；freshness meta 暴露 `covered/total/ratio`，<99% 显示 lagging | 不为不可达的 US/GLOBAL 指数伪造行情，单独标注「免费源不可得」 |
| legacy 旧链 hfq | hfq 只有 124 只配置（universe 287），旧分母导致覆盖率恒 0.43、state 卡 11-24、backlog 积压 | `expected_count(...,adjust)` 按 adjust_modes 过滤分母；新增 `scripts/backfill_legacy_quotes.py`（v3/免费源补 raw 含 hfq → repair clean），dry-run/apply | 不用 bfq 冒充 hfq；不跨源混用绝对基准（按重叠日重锚） |
| 跨源 PE 校验 | 中证官网两列是「总股本/计算用股本」而非静态/滚动；旧代码把 PE2 当 pe_ttm（000300 与平安差 ~14%） | 修正：PE1(总股本)→pe_ttm（与平安差 4.4%<5%）；PE2 仅审计保留、pe_static 留空；csindex_value 整数日按 %Y%m%d 解析并过滤 1970 脏行 | 不把「计算用股本 PE」标成静态 PE，不用 PEG 反推 |
| 市场估值/10Y 历史 | 历史深度取决于源上线时间，短期无法与 A 股 1980 年以来历史对齐 | 从本轮起每日积累；freshness/audit 显示覆盖起点 | 不批量生成假历史 |

## 3. 部署顺序（不自动执行）

1. 应用迁移：`ddl/82_market_data_audit.sql`（体检表 + `csindex_oss` 源注册）；
2. 重启 API（新增 `GET /api/v1/market/data-health`）；
3. 按 §1 加入 cron（先 `python scripts/daily_data_audit.py --dry-run` 冒烟）；
4. 一次性回填（按需）：`index_quotes_free.py --symbols 000985 --start 2017-01-01`、
   `backfill_legacy_quotes.py --apply`、`risk_free.py --start 2017-01-01`；
5. 观察 09:30 体检报告：error=0 为通过；error>0 时脚本 exit 1，看 `bp_etl_quality_issue`。
