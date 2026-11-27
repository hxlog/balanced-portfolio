# 一篮子资产风险平价（P4）

> 实现：`bp_api/quant/basket.py`（优化器 + 回测引擎）、`bp_api/basket.py`（HTTP 端点）、
> `bp_api/schemas.py`（请求模型）、`bp_api/tests/test_basket.py`（38 个用例）。
> 数据只读 `bp_quote_clean`；端点不落库、不派发任务，属于同步计算接口。

## 1. 与四象限组合方法的区别

| 维度 | 四象限组合（现有） | 一篮子（P4） |
|---|---|---|
| 资产组织 | 必须先映射到 overheat / stagflation / recovery / recession | 不划分象限，直接给定资产池 |
| 方法数 | 4 种（象限内最大夏普 × 象限间 ERC 等） | 6 种（见下表） |
| 方法标识 | `quadrant_inner_sharpe_outer_rp` 等 | `risk_parity` / `max_sharpe` / `max_sortino` / `min_variance` / `equal_weight` / `risk_budget` |
| 风险预算 | 仅 `sharpe_sq_risk_budget`（预算 ∝ 夏普²） | `risk_budget` 支持任意非负预算（默认等风险贡献） |
| 结果去向 | 落 `bp_backtest_*`，供 `/dashboard` 轮询读取 | 请求内直接返回，不落库；适合 `/builder` 实时预览 |
| 集中度限制 | 支持 `max_weight` | 当前端点未暴露 `max_weight`（前端可先做展示/校验，后续版本再扩展） |

两套实现共用同一套底层能力：`quant/optimizer.py` 的 ERC/CCD、SLSQP 最大比率求解、
协方差正则化，以及 `quant/metrics.py` 的年化/回撤口径。

## 2. 六种方法

| method | 经济含义 | 求解方式 | 退化处理 |
|---|---|---|---|
| `risk_parity` | 等风险贡献（ERC）：每个资产对组合波动的贡献相等 | Spinu 循环坐标下降（CCD），复用 `risk_parity_weights` | 协方差收缩 + ridge；失败回退等权 |
| `max_sharpe` | 最大化 `(μ·w − r_f) / σ_p` | SLSQP + 逆波动率热启动 `x0`，复用 `max_ratio_weights` | 不收敛/NaN 回退逆波动率权重 |
| `max_sortino` | 最大化 `(μ·w − r_f) / 下行波动` | 同上（目标函数改用下偏标准差） | 同上 |
| `min_variance` | 最小化 `wᵀΣw` | 解析解 `w ∝ Σ⁻¹1`，负权重截断后归一 | 奇异矩阵用 `pinv`；全截断时回退逆波动率 |
| `equal_weight` | 有效资产等权 | 闭式 | 无 |
| `risk_budget` | 各资产风险贡献 ∝ 自定义预算 `b_i` | CCD 解 `min ½wᵀΣw − Σ b_i ln w_i` | 预算缺省=ERC；预算未覆盖有效资产→400 |

### 2.1 风险预算约定

- `risk_budget` 是 `{资产 key: 预算}`，资产 key 为 `symbol@source`（如 `000300@cn_index_em`）。
- 预算必须**非负、有限、合计 = 1**（容差 `1e-6`）；不满足返回 400。
- 未提供 `risk_budget` 时，`risk_budget` 方法等价于 `risk_parity`（等风险贡献）。
- 回测中若部分资产尚未攒够窗口，预算会在**当前可用资产**上重新归一；若可用资产都没有预算，
  退化为等预算（不报错），避免晚上市资产阻断整个组合。
- **分组预算**（股票/债券/商品/海外）属于前端交互层：前端按分组配置后，展开为每个资产的
  `symbol@source` 预算再调用本接口。后端只认单资产预算，避免分组口径在服务端重复定义。

### 2.2 无未来函数与窗口

- `optimize(..., lookback=L)` 只使用传入矩阵的**最后 L 行**；不会读取窗口之外的数据。
- 回测逐日重算：第 `t` 日收盘后用截至 `t` 的收益求目标权重，`t+1` 日才使用该权重。
- 窗口不足 2 个观测、全部资产无有效值等情形回退等权，不抛异常。
- 收益率构造：`bp_quote_clean` 中 `fill_flag='interp'` 的行在
  `repositories._load_series` 已置 NaN；回测引擎 `ffill()` 后 `pct_change()`，
  缺口日收益为 0、复牌日收益为真实缺口收益，不依赖右锚未来价格。

## 3. API

两个端点均挂 `Depends(auth.optional_user)`：匿名可调用，登录用户也可调用；
当前不区分用户额度，也不写入任何表。`main.py` 的注册由主控完成，
`bp_api/basket.py` 只提供 `register_routes(app)`。

### 3.1 `POST /api/basket/optimize`

请求：

```json
{
  "assets": [
    {"symbol": "000300", "source": "cn_index_em"},
    {"symbol": "10Y", "source": "bond_csi_treasury"},
    {"symbol": "AU", "source": "gold_comex_em"}
  ],
  "method": "risk_parity",
  "lookback_days": 156,
  "risk_free": 0.02,
  "risk_budget": null,
  "start": null,
  "end": null
}
```

响应（权重按请求资产顺序返回；未获得有效历史的资产权重为 0）：

```json
{
  "method": "risk_parity",
  "weights": [
    {"symbol": "000300", "source": "cn_index_em", "weight": 0.31},
    {"symbol": "10Y", "source": "bond_csi_treasury", "weight": 0.52},
    {"symbol": "AU", "source": "gold_comex_em", "weight": 0.17}
  ],
  "diagnostics": {
    "method": "risk_parity",
    "lookback": 156,
    "effective_start": "2025-03-20",
    "n_obs": 156,
    "volatility": 0.0831,
    "sharpe": 0.74,
    "annualized_return": 0.0615,
    "active_assets": 3
  }
}
```

字段口径：

| 字段 | 含义 |
|---|---|
| `diagnostics.lookback` | 请求的 `lookback_days`（原样回显） |
| `diagnostics.n_obs` | 实际参与优化的日收益观测数（通常等于 `lookback`） |
| `diagnostics.effective_start` | 窗口首个收益日 |
| `diagnostics.volatility` | 组合日收益年化波动（`std(ddof=1) × √trading_days`） |
| `diagnostics.sharpe` | `(年化收益 − risk_free) / 年化波动`，与 `/dashboard` 同口径 |
| `diagnostics.active_assets` | 权重 > 0 的资产数 |

窗口规则：

- 未传 `start` 时，要求清洗行情至少覆盖 `lookback_days` 个交易日；不足返回 400。
- 传了 `start` 时，先用 `[start, end]` 内的收益样本，再取最后 `lookback_days` 行；
  此时允许样本短于 `lookback_days`（但至少 2 行），便于用户主动缩短区间。
- `end` 会截断价格面板，只使用 `<= end` 的数据。

### 3.2 `POST /api/basket/backtest`

在 optimize 入参基础上增加 `rebalance_band`（绝对值，默认 `0.05`）：

```json
{
  "assets": [
    {"symbol": "000300", "source": "cn_index_em"},
    {"symbol": "10Y", "source": "bond_csi_treasury"}
  ],
  "method": "risk_budget",
  "lookback_days": 156,
  "risk_free": 0.02,
  "risk_budget": {"000300@cn_index_em": 0.6, "10Y@bond_csi_treasury": 0.4},
  "rebalance_band": 0.05,
  "start": "2020-01-02",
  "end": null
}
```

响应（`nav` 为完整逐日序列，示例省略中间点）：

```json
{
  "method": "risk_budget",
  "effective_start": "2020-06-01",
  "lookback": 156,
  "n_obs": 1380,
  "nav": [
    {"trade_date": "2020-06-01", "nav": 1.0, "ret": 0.0},
    {"trade_date": "2020-06-02", "nav": 1.0012, "ret": 0.0012}
  ],
  "annualized_return": 0.0712,
  "annualized_vol": 0.0923,
  "max_drawdown": -0.121,
  "sharpe": 0.55,
  "turnover": 0.84,
  "turnover_total": 4.73,
  "rebalance_count": 17,
  "weights": [
    {"symbol": "000300", "source": "cn_index_em", "weight": 0.58},
    {"symbol": "10Y", "source": "bond_csi_treasury", "weight": 0.42}
  ],
  "contributions": [
    {
      "key": "000300@cn_index_em",
      "symbol": "000300",
      "source": "cn_index_em",
      "avg_weight": 0.57,
      "asset_return": 0.41,
      "contribution": 0.061
    }
  ],
  "rebalances": [
    {
      "trade_date": "2020-06-01",
      "reason": "建仓",
      "target_weights": {"000300@cn_index_em": 0.6, "10Y@bond_csi_treasury": 0.4},
      "prev_weights": null,
      "delta": null,
      "max_deviation": 0.0,
      "turnover": 1.0
    }
  ],
  "metrics": {"annualized_return": 0.0712, "annualized_vol": 0.0923, "max_drawdown": -0.121}
}
```

口径说明：

| 字段 | 含义 |
|---|---|
| `nav[].nav` | 单位净值（建仓日 = 1.0；当前端点不计手续费/滑点） |
| `nav[].ret` | 当日组合收益，满足 `nav_t = nav_{t-1} × (1 + ret_t)` |
| `annualized_return` / `annualized_vol` / `max_drawdown` / `sharpe` | 复用 `quant/metrics.py` |
| `turnover` | **年化**双边换手率 = `turnover_total × trading_days / n_obs` |
| `turnover_total` | 区间累计双边换手（建仓 0→目标计 1.0） |
| `rebalance_count` | 含建仓的调仓次数 |
| `weights` | 最近一次调仓的目标权重 |
| `contributions[].contribution` | Carino 链接后的逐资产收益贡献；合计≈组合总收益 |
| `rebalances[].max_deviation` | 触发本次再平衡前的最大单资产偏离（绝对值） |

再平衡语义与 `quant/backtest.py` 完全一致：

1. 每个交易日收盘后，用截至当日的滚动窗口重算目标权重；
2. 先让实际权重随当日收益自然漂移；
3. 若任一资产 `|实际 − 目标| > rebalance_band`，**整体**回到当日目标；
4. 当日 NAV 用当日收益更新，新权重次日生效。

成分逐步纳入：窗口内真实收盘日不足 `min_window` 的资产权重为 0，不拖后整体
`effective_start`。`min_window` 由服务端 `BP_MIN_WINDOW`（默认 60）控制，
并被自动收紧到不超过 `lookback_days`。

### 3.3 错误码

| 状态码 | 场景 |
|---|---|
| 400 | 未知 `method`；`risk_budget` 为负/含 NaN/合计≠1/含未知资产；`lookback_days` 不足；重复资产；区间无有效样本；回测历史不足 |
| 404 | 请求的资产在 `bp_quote_clean` 中无清洗行情（需先运行 ingest/clean） |
| 422 | Pydantic 入参校验失败（空资产列表、`lookback_days < 2`、`rebalance_band` 越界、`start > end` 等） |

## 4. 前端接入建议

1. `/builder` 的「一篮子」模式调用 `POST /api/basket/optimize` 预览目标权重：
   - 方法切换时只改 `method` 重新请求；
   - 风险预算滑杆变化时传 `risk_budget`（key 用 `symbol@source`），前端先校验合计 100%；
   - 用 `diagnostics.volatility` / `sharpe` 展示当前组合的即时风险收益特征。
2. 「开始回测」调用 `POST /api/basket/backtest`：
   - `nav` 直接喂 ECharts 折线图；
   - `contributions` 展示逐资产贡献条形图；
   - `turnover` / `turnover_total` 展示调仓频率；
   - `rebalances` 可在图表上打点，hover 显示 `reason` 与 `max_deviation`。
3. 常量镜像：前端方法下拉框必须与 `bp_api/quant/basket.py` 的 `METHODS` 保持一致，
   建议在 `web/lib/api.ts` 增加 `BASKET_METHOD_OPTIONS` 并在切换时校验。
4. 鉴权：端点是 `optional_user`，匿名可直接调用；若后续要限制额度，在控制器层加
   `require_user` 或用户级限流即可，不影响本模块。
5. 路由注册：`main.py` 中加入
   ```python
   from . import basket as _basket
   _basket.register_routes(app)
   ```
   由主控统一完成。

## 5. 测试与复现

```bash
python -m pytest bp_api/tests/test_basket.py -q
# 38 passed
```

覆盖：6 方法合法权重、权重和=1、长仓、单资产/单有效资产、完全相关退化、全零方差、
空窗口/单行窗口、lookback 只取尾部、风险预算比例与非法预算、最小方差/最大夏普的
经济含义、回测日汇总一致性、无未来函数、再平衡带语义、换手率与逐资产贡献、
成分逐步纳入、两个路由的 400/404/权限依赖与 schema 校验。

## 6. 持久化与示例篮子（ddl/70 + ddl/78）

> 实现：`bp_api/baskets.py`（CRUD + 服务端重算）、`bp_api/basket.py:build_latest_result`（重算核心，
> 与 `POST /api/basket/backtest` 同一引擎）、`ddl/78_basket_demo.sql`（is_demo/display_order）、
> `scripts/seed_demo_basket.py`（12 只 A 股示例，幂等）。
> 前端客户端：`web/lib/basket-api.ts` / `web/lib/basket-demo.ts`（字段与权限口径需保持一致）。

### 6.1 示例篮子语义（与 bp_portfolio demo 组合一致）

| 操作 | 匿名 | 登录普通用户 | 管理员 |
|---|---|---|---|
| 列表示例（is_demo=TRUE） | ✅ | ✅ | ✅ |
| 列表自己的非示例篮子 | — | ✅ | ✅ |
| 列表全部篮子 | — | — | ✅ |
| 查看示例详情 | ✅ | ✅ | ✅ |
| 查看他人私有篮子 | 403 | 403 | ✅ |
| 复制（POST /copy） | 401 | ✅ 得到自己的非示例副本 | ✅ |
| 编辑/删除示例 | 403 | 403（即使 owner 也不行） | ✅ |
| 编辑/删除自己的非示例 | — | ✅ | ✅ |
| 服务端重算（POST /recompute） | 401 | 403 | ✅ |

- `GET /api/baskets` 支持可选 `?scope=demo|mine`：匿名 scope=demo 返回示例、scope=mine 返回空数组
  （不 401，便于前端并行拉取合并）；登录用户不传 scope = 示例 + 自己的（兼容旧行为）。
- 列表行新增 `is_demo`（bool）与 `display_order`（int|null）；示例按 display_order 升序
  （NULLS LAST）、自己按 updated_at 倒序，示例恒排在前。
- 示例篮子的 `latest_result` **只能由服务端 recompute 生成**：PATCH 带 latest_result 会 400；
  非示例篮子保持原有行为（保存时可直接带 latest_result 摘要）。
- `POST /api/baskets/{id}/recompute`（仅 `require_super_admin`）：同步读取 `bp_quote_clean`
  重算，写 latest_result 并刷新 updated_at；数据缺失返回 404、参数/方法非法返回 400，不写库、不伪造。

latest_result 结构（由 `build_latest_result` 生成；前端列表摘要读顶层
`annualized_return / max_drawdown / sharpe`）：

~~~json
{
  "method": "risk_parity",
  "as_of": "2026-11-27",
  "computed_at": "2026-11-27T21:10:00+08:00",
  "effective_start": "2021-02-05",
  "lookback_days": 156,
  "rebalance_band": 0.05,
  "risk_free": 0.0,
  "n_obs": 1400,
  "annualized_return": 0.141,
  "annualized_vol": 0.21,
  "max_drawdown": -0.32,
  "sharpe": 0.55,
  "turnover": 0.4,
  "turnover_total": 2.3,
  "rebalance_count": 12,
  "assets": [{"symbol": "600519", "source": "etl_a_stock"}],
  "weights": [{"symbol": "600519", "source": "etl_a_stock", "weight": 0.08}],
  "nav": [{"trade_date": "2021-02-05", "nav": 1.0, "ret": 0.0}]
}
~~~

### 6.2 12 只 A 股示例（seed）

`scripts/seed_demo_basket.py` 幂等写入「A股核心资产 12 只（示例）」（is_demo=TRUE、display_order=0、
owner_user_id=NULL、method=risk_parity、默认参数 lookback_days=156 / rebalance_band=0.05 / risk_free=0）：

贵州茅台 600519、宁德时代 300750、招商银行 600036、中国平安 601318、五粮液 000858、美的集团 000333、
长江电力 600900、紫金矿业 601899、比亚迪 002594、恒瑞医药 600276、隆基绿能 601012、海天味业 603288
（source=`etl_a_stock`，后复权 hfq，2020-11 起）。

~~~bash
# 前置：ddl/78（已部署环境）
psql -h <host> -U postgres -d balanced_portfolio -f ddl/78_basket_demo.sql

# seed（默认随后用服务端同一实现重算 latest_result，绝不伪造）
python scripts/seed_demo_basket.py

# 只 seed、稍后由管理员调 recompute
python scripts/seed_demo_basket.py --no-recompute
# 只打印现状不写库
python scripts/seed_demo_basket.py --dry-run
~~~

幂等：按 (is_demo=TRUE, name) 查找，存在则更新定义（assets/params/method/description/display_order），
重复执行不产生重复行；缺失 `bp_index_config(etl_a_stock)` 资产或缺失 ddl/78 列时会给出明确报错。

### 6.3 测试与迁移

~~~bash
python -m pytest bp_api/tests/test_baskets_api.py bp_api/tests/test_basket.py -q
~~~

覆盖：_can_view/_can_edit 权限矩阵、匿名只读示例、登录示例+自己、admin 全部、scope 筛选、
复制需登录且得到非示例副本、示例仅 admin 可编辑/删除、PATCH latest_result 防伪造、
recompute 写 latest_result（成功/404/400 分支与依赖声明）、ddl/78 幂等、seed 定义与幂等。

迁移（已部署环境只跑未应用的编号；全新环境按 schema.sql 基线流程）：
`ddl/78_basket_demo.sql`（2 × ADD COLUMN IF NOT EXISTS + 1 × CREATE INDEX IF NOT EXISTS，
可重复执行）。`deploy/deploy.sh` 不会执行迁移，需手动执行后再重启 bp-api / bp-web。

