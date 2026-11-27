# 基金风险指标与跟踪误差（bp_fund_risk）

> 实现：`scripts/compute_fund_risk.py`（净值口径 / 基准口径 / 断点检测 / 全量重算）。
> 数据：`bp_fund_nav_daily`（场外基金累计净值）、`bp_etf_quote_daily`（场内 ETF 后复权）、
> `bp_index_quote_daily`（基准指数 / HKDCNY 汇率）、`bp_index_tracker_fund`（基金→主跟踪指数）。
> 结果表：`bp_fund_risk`（as_of = 净值最后一日；updated_at = 计算时间）。

## 1. 背景：50.57% 跟踪误差事故

旧版脚本直接用单位净值 `nav` 计算收益率。以 **SH513660（华夏沪港通恒生ETF）** 为例：
该基金 2026-04-20 因份额折算，单位净值单日 -49.63%，而累计净值 `acc_nav` 连续。
旧口径把这次拆分当成一天 -49.63% 的"亏损"，导致 vs HSI 的 1 年跟踪误差被抬高到
**50.57%**（2026-11-15 生产值），收益类指标（ret_1y = -56.98%）也全部失真。

修复后同数据（2026-11-27 只读核算）：

| 净值口径 | 基准口径 | 1y 跟踪误差 |
|---|---|---|
| 单位净值 nav（旧） | HSI 价格指数 | 50.57% |
| 累计净值 acc_nav | HSI 价格指数 | **4.31%** |
| 累计净值 acc_nav | HSI 价格指数 × HKDCNY（本脚本默认） | **4.82%** |

> 4.31% 是"acc_nav 直接对 HSI 价格指数"的结果（原型稿采用该数字）；本脚本按 2026-11-27
> 方案要求把人民币计价基金与港币计价指数做汇率调整（HSI × HKDCNY），故生产重算结果
> 约 4.82%（仍在 5% warning 阈值内，量级正确）。若需要复现 4.31%，用 `--hsi-basis price`。

## 2. 口径

### 2.1 净值主口径（按优先级）

1. **`bp_fund_nav_daily.acc_nav`（累计净值，含分红再投）** —— 主口径；
   覆盖不足（该基金 acc 有效观测 < 60，或不足 nav 行数的 90%）时进入回退。
2. **`bp_etf_quote_daily` 的 `hfq` 后复权** —— 场内 ETF 回退口径：
   - 基金代码去掉 `SH/SZ/OF` 前缀归一为 `etf_code`（`SH513660 → 513660`）；
   - 同一只 ETF 可能有多源 hfq 行：只取**覆盖最长的一个源**（优先级
     `tencent_etf_kline > em_kline:anchored > sina_etf_kline > tencent_kline > sina_etf_kline:factor`），
     不混用不同来源的绝对价基数；按交易日去重对齐。
   - 2026-11-27 生产数据：1294 只跟踪基金中 1268 只 acc 全程可用；26 只无 acc 的
     场内基金全部有 `tencent_etf_kline` hfq 可回退。
3. **单位净值 `nav`** —— 两者都缺时的最后兜底（basis=nav；分红偏差无法完全修复，
   仅靠断点修正拆分造成的水平跳变）。

### 2.2 基准

- 基准 = 基金的**主跟踪指数**：取该基金最新跟踪日 AUM 合计最大的 index_code
  （旧实现按全历史 AUM 求和，会把历史上 AUM 大的指数权重放大，已修正）。
- 每个指数取库内 `adjust='bfq'`、覆盖最长的**单一 source** 的价格序列
  （避免同指数多源基线不同导致收益跳变）。
- **HSI 口径**：优先使用全收益序列（若库内存在 `HSI_TR / HSITR / HSI-TR / HSI全收益`
  之一的 symbol）；当前无免费全收益源，回退 **HSI 价格指数 × HKDCNY**（`fx_sina`，
  按指数交易日 reindex + ffill，只用过去汇率、不引入未来数据），口径 `hsi_price_x_hkdcny`。
  其他指数暂按价格指数（不含汇率调整，属本任务范围外）。
- 口径开关：`--hsi-basis auto|hsi_total_return|price_x_hkdcny|price`；
  默认 `auto`（全收益→价格×汇率→纯价格）。

### 2.3 净值断点检测（单日 |收益| > 30%）

计算指标前先对选定的净值序列做断点检测（`detect_and_repair_breaks`）：

| 情形 | 判定 | 处理 | 记录 kind |
|---|---|---|---|
| 单日尖刺、次日反向抵消（对数收益和 ≈ 0） | 坏点 | 剔除该日 | `spike_removed` |
| 水平跳变（份额拆分/折算/数据重定基） | 断点 | 断点因子缩放断点前段，使序列连续；断点前各段内部收益不变，断点当日收益≈0 | `level_shift` |
| 单位净值跳变但同日期累计净值连续 | 拆分（已用 acc_nav，无需修正） | 采用 acc_nav，交叉记录审计信息 | `nav_split_ignored` |

事件明细写入 `--report` 的 JSON（`repair_events` / `nav_split_events`），
stdout 只打印汇总。2026-11-27 生产数据：跟踪基金里有 185 只曾发生单位净值拆分
（210 个断点）、累计净值断点 7 个（4 只基金，2022 年数据重定基），脚本会分别修正/记录。

## 3. 指标口径（与旧版一致）

- `as_of`：所选净值序列最后一日；`n_obs`：净值观测数（< 60 不写）。
- `ret_1y` 为区间总收益；`ret_3y_ann / ret_5y_ann` 年化；`ytd` 年初至今。
- `ann_vol_1y` = 最近 252 个日收益标准差 × √252；`max_dd_1y` 同期最大回撤。
- `tracking_error_1y` = 最近 252 个**对齐**日收益差（基金−基准）的标准差 × √252，单位百分数点
  （如 4.31 表示 4.31%）；`info_ratio_1y` = (基金 1y 收益 − 基准年化) / TE。
- `benchmark_code`：主跟踪指数代码（HSI 等）；`updated_at`：写入时间（数据库 now()）。

## 4. 运行

~~~bash
# 全量重算（跟踪基金全集；生产 1328 只跟踪基金中 1294 只有净值，bp_fund_risk 现有 1147 行）
python scripts/compute_fund_risk.py

# 单只调试（打印 nav_basis / benchmark_basis / TE）
python scripts/compute_fund_risk.py --fund SH513660

# 只计算不写库 + 输出断点明细报告（可先在只读环境验证）
python scripts/compute_fund_risk.py --dry-run --report /tmp/fund_risk.json

# 复现"acc_nav vs HSI 价格指数"口径（原型 4.31%）
python scripts/compute_fund_risk.py --hsi-basis price

# 清理不在本次结果中的旧行（如基金退市/移除）
python scripts/compute_fund_risk.py --prune
~~~

参数：`--batch-size`（每批基金数，默认 150，控制内存）、`--verbose`（逐批日志）。
输出汇总：universe/computed/rows_written、nav_basis 与 benchmark_basis 计数、断点修正数、
nav 拆分交叉记录数、跳过原因、耗时。写 `bp_fund_risk` 为幂等 upsert（ON CONFLICT fund_code），
`as_of` / `updated_at` 每次重算刷新。

**调度建议**：基金净值（bp_etl fund_nav，20:00 波次）与指数行情完成之后运行
（如 21:30 / 23:50 各一次）；只在服务端进程外跑（脚本直连数据库），不占 API 请求路径。

### 4.1 2026-11-27 生产只读 dry-run 实测（`--dry-run`，未写库）

- universe 1328 只跟踪基金，computed 1228，skipped 66（历史不足 60 日）；
- nav_basis：acc_nav 1202 / etf_hfq 26（26 只无累计净值的场内基金全部成功回退）；
- benchmark_basis：price 1101 / **hsi_price_x_hkdcny 5** / missing 122；
- 断点修正 5 处（level_shift 3 + spike_removed 2）；nav 拆分交叉记录 205 处；
- **SH513660：TE 1y = 4.82%**（旧 50.57%），ret_1y = -13.95%（旧 -56.98%）；
  5 只 HSI 跟踪基金 TE 4.61%–4.82%；
- 全表 TE 中位数 2.77%（旧表 5.68%）、TE>20% 的基金 328 只（旧表 454 只）。
  剩余高 TE 主要是 `bp_index_quote_daily` 的指数行情覆盖/质量问题：如 931151 与其
  对应 ETF 的日收益相关系数仅 0.435（ETF 与基金净值 corr 0.99），需 task-1 的
  指数行情免费源聚合/clean 修复后重跑本脚本再降；`missing` 122 亦同源（指数无行情）。
- 全量 dry-run 耗时约 218s（弱机/生产建议错峰，`--batch-size 150`）。

## 5. 测试

~~~bash
python -m pytest bp_api/tests/test_fund_risk.py -q
~~~

覆盖：代码归一、断点修复（水平跳变/尖刺）、acc→ETF→nav 回退优先级、513660 类样本
（新口径 TE ≈ 4.3% / 旧 nav 口径 ≈ 50%）、HSI×HKDCNY 基准口径、`recompute_all` 批量编排与 upsert。

## 6. 无 schema 变更

本任务只改计算口径与重算脚本，`bp_fund_risk` 表结构不变（as_of / updated_at 均为 68 号
迁移已有列），无需数据库迁移。基准口径（price_x_hkdcny）是计算属性，不单独落库；
HSI 详情页脚注由前端静态标注（见 docs/design/2026-11-27-unified-redesign/）。
