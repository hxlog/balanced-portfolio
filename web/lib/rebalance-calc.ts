/**
 * 调仓计算器的全部金额算法。
 *
 * 设计: 纯函数、无 React、无 IO —— 便于单测, 且方便在浏览器本地计算时保持
 * 「金额不上传」的隐私承诺(只有标的代码会进请求)。
 *
 * 口径(与后端 backtest.py 的交易成本模型同源):
 *   计划持仓 = 最优权重 × 拟投资金额
 *   买入 = max(0, 计划 − 当前),  卖出 = max(0, 当前 − 计划)
 *   佣金/滑点 = (Σ买 + Σ卖) × 费率,  印花税 = Σ卖 × 费率
 */

/** 场内 ETF 最小交易单位(份)。 */
export const LOT_SIZE = 100;

export type CalcRow = {
  key: string;
  name: string;
  symbol: string;
  source: string;
  /** bp_index_config.category: index/etf/commodity/bond/crypto/forex */
  category?: string;
  /** 目标权重(小数 0~1) */
  targetWeight: number;
  /** 上期权重(小数); null/undefined 表示上期无此标的 */
  prevWeight?: number | null;
};

function safeAmount(amount: number): number {
  return Number.isFinite(amount) && amount > 0 ? amount : 0;
}

/**
 * 历史调仓日的「当前持仓」默认值 = 上期权重 × 拟投资金额。
 *
 * 用上期权重而非 actual_holdings: 对任意历史调仓日恒可算(actual_holdings 只对
 * 数据截止日有意义)。
 *
 * 注意: prevWeight=0 与「无上期持仓」都返回 0, 两者不可区分 —— 本函数只提供
 * 「历史调仓日的当前持仓」默认值; 「最近交易日」口径的当前持仓由调用方传入
 * actual_holdings 覆盖(见 Dashboard 的 currentByKey)。
 */
export function defaultCurrentByPrev(
  rows: CalcRow[],
  amount: number,
): Record<string, number> {
  const base = safeAmount(amount);
  const out: Record<string, number> = {};
  for (const r of rows) {
    const w = Number.isFinite(r.prevWeight as number) ? (r.prevWeight as number) : 0;
    out[r.key] = Math.round(Math.max(0, w) * base);
  }
  return out;
}

export type CalcLine = {
  key: string;
  targetWeight: number;
  /** 当前持仓金额(元) */
  currentAmount: number;
  /** 计划持仓金额(元) = 权重 × 拟投资金额 */
  targetAmount: number;
  buy: number;
  sell: number;
  /** ETF 取整后可成交份额(100 的整数倍); 非 ETF 或无价格时为 null */
  buyShares: number | null;
  sellShares: number | null;
  /** 取整后未成交的零头(元); 非 ETF 为 0 */
  buyRemainder: number;
  sellRemainder: number;
};

export type Rates = {
  feeRate: number;
  slippageRate: number;
  stampDutyRate: number;
};

/**
 * 计划持仓金额 = 权重 × 拟投资金额。
 *
 * 逐行四舍五入会让各行之和偏离整额(后端权重按 6 位小数落库, 往往 Σ权重 = 0.999999),
 * 故把**舍入残差**补给权重最大的那一行, 使 Σ 严格等于 `round(Σ权重 × 拟投资金额)`。
 *
 * 两条边界(均有回归测试):
 *
 * - **残差不补给「排序最后」的行。** 调仓变动表按 |Δ| 升序排, 目标权重为 0 的清仓行
 *   |Δ| = 上期权重, 常常排在最后。老实现把残差给它, 等于给一个目标为零的标的凭空造出
 *   计划持仓 —— 实测 2024-09-30 期 `000510@cn_index_em`(目标 0.000000)被分到 ¥204,
 *   于是它算出「卖出 673」而正确答案是清仓卖出 877, 少卖 23%, 用户照做会留下残仓。
 *
 * - **Σ权重 < 1 时不缩放。** 未分配的权重属于压根没出现在这张表里的标的(被噪声阈值
 *   滤掉的残值行), 摊给任何一行都是无中生有。此时 Σ计划 = `round(Σ权重 × 金额)`。
 *   只有 Σ权重 > 1(调用方传了未归一的权重)才按 `1/Σ` 缩回, 以免「买入合计」超过用户
 *   自己填的拟投资金额。
 */
export function targetAmounts(rows: CalcRow[], amount: number): Record<string, number> {
  const base = Math.round(safeAmount(amount));
  const out: Record<string, number> = {};
  if (rows.length === 0) return out;
  const w = rows.map((r) => Math.max(0, Number.isFinite(r.targetWeight) ? r.targetWeight : 0));
  const sumW = w.reduce((s, x) => s + x, 0);
  const scale = sumW > 1 ? 1 / sumW : 1;
  const scaled = w.map((x) => x * scale * base);
  const rounded = scaled.map((x) => Math.round(x));
  const residual = Math.round(sumW * scale * base) - rounded.reduce((s, x) => s + x, 0);
  rows.forEach((r, i) => {
    out[r.key] = rounded[i];
  });
  if (residual !== 0) {
    // 补给权重最大的行(并列取首个): 它一定存在, 且残差相对它足够小, 不会把它压到负数。
    let k = 0;
    for (let i = 1; i < w.length; i++) if (w[i] > w[k]) k = i;
    out[rows[k].key] = Math.max(0, out[rows[k].key] + residual);
  }
  return out;
}

/** 逐行算出买入/卖出金额。`0` 是合法金额。 */
export function computeLines(
  rows: CalcRow[],
  current: Record<string, number>,
  target: Record<string, number>,
): CalcLine[] {
  return rows.map((r) => {
    const cur = Number.isFinite(current[r.key]) ? current[r.key] : 0;
    const tgt = Number.isFinite(target[r.key]) ? target[r.key] : 0;
    const diff = tgt - cur;
    return {
      key: r.key,
      targetWeight: r.targetWeight,
      currentAmount: cur,
      targetAmount: tgt,
      buy: diff > 0 ? diff : 0,
      sell: diff < 0 ? -diff : 0,
      buyShares: null,
      sellShares: null,
      buyRemainder: 0,
      sellRemainder: 0,
    };
  });
}

/** 按 100 份/手向下取整, 返回可成交份额、对应金额与未成交零头。 */
export function lotRound(
  amount: number,
  price: number,
): { shares: number; cash: number; remainder: number } {
  if (!Number.isFinite(amount) || amount <= 0) {
    return { shares: 0, cash: 0, remainder: 0 };
  }
  if (!Number.isFinite(price) || price <= 0) {
    return { shares: 0, cash: 0, remainder: amount };
  }
  // +1e-9 抵御浮点误差: amount 恰为整手金额时 floor 不应少算一手
  const lots = Math.floor(amount / (price * LOT_SIZE) + 1e-9);
  const shares = lots * LOT_SIZE;
  const cash = shares * price;
  // 上面那个 epsilon 可能让 cash 极微小地超过 amount(浮点残渣), 负零头会被
  // toFixed(2) 渲染成 "-0.00"。金额列不可显示负零头, 故钳到 0。
  return { shares, cash, remainder: Math.max(0, amount - cash) };
}

/**
 * 仅对场内 ETF 换算份额(指数/商品/债券无「份额」概念); 无价格时原样返回,
 * 调用方据此隐藏份额列。
 */
export function applyShares(
  lines: CalcLine[],
  rows: CalcRow[],
  priceByKey: Record<string, number>,
): CalcLine[] {
  const byKey = new Map(rows.map((r) => [r.key, r]));
  return lines.map((l) => {
    const r = byKey.get(l.key);
    const px = priceByKey[l.key];
    if (!r || r.category !== "etf" || !Number.isFinite(px) || px <= 0) return l;
    const b = lotRound(l.buy, px);
    const s = lotRound(l.sell, px);
    return {
      ...l,
      buyShares: b.shares,
      sellShares: s.shares,
      buyRemainder: b.remainder,
      sellRemainder: s.remainder,
    };
  });
}

export function computeTotals(lines: CalcLine[]): {
  buyTotal: number;
  sellTotal: number;
  turnover: number;
  remainder: number;
} {
  let buyTotal = 0;
  let sellTotal = 0;
  let remainder = 0;
  for (const l of lines) {
    buyTotal += l.buy;
    sellTotal += l.sell;
    remainder += l.buyRemainder + l.sellRemainder;
  }
  return { buyTotal, sellTotal, turnover: buyTotal + sellTotal, remainder };
}

/**
 * 交易费用。成本模型(结构)与后端 backtest.py 同源:
 *   cost = turnover × (佣金 + 滑点) + sell_turnover × 印花税
 * 三个费率均由调用方从组合自身参数传入(portfolio 的 fee_rate / slippage_rate /
 * stamp_duty_rate), 本函数不对费率取值做任何假设。
 */
export function computeFees(
  buyTotal: number,
  sellTotal: number,
  rates: Rates,
): { commission: number; slippage: number; stampDuty: number; total: number } {
  const turnover =
    (Number.isFinite(buyTotal) ? buyTotal : 0) + (Number.isFinite(sellTotal) ? sellTotal : 0);
  const sell = Number.isFinite(sellTotal) ? sellTotal : 0;
  const commission = turnover * Math.max(0, rates.feeRate || 0);
  const slippage = turnover * Math.max(0, rates.slippageRate || 0);
  const stampDuty = sell * Math.max(0, rates.stampDutyRate || 0);
  return { commission, slippage, stampDuty, total: commission + slippage + stampDuty };
}
