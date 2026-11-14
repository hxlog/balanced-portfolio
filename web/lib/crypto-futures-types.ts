/**
 * 加密合约看板 API 类型。
 *
 * 数据源：GET /api/crypto/futures/{summary,contracts,{code}/series}
 * 后端只读 bp_crypto_futures_snapshot_5m / bp_crypto_futures_percentile
 * 预计算表，请求路径不做计算。
 */

/** 后端统一响应信封。 */
export interface CryptoFuturesApiEnvelope<T> {
  data: T;
  meta?: Record<string, unknown>;
  error?: string | null;
}

export interface CryptoFuturesSummary {
  /** 活跃合约数（有 OI 排名的合约）。 */
  contracts: number;
  /** 全市场 OI 名义值合计，原生 USDT。 */
  total_oi_notional: number;
  /** 按 OI 名义值加权的多空账户比；无有效 OI 时为 null。 */
  weighted_long_short_ratio: number | null;
  /** 主动买卖比（taker buy/sell）中位数；无样本时为 null。 */
  median_taker_buy_sell_ratio: number | null;
  /** 最近快照时间（UTC ISO 字符串）。 */
  latest_captured_at: string | null;
}

export interface CryptoFuturesPercentile {
  /** 0~100；后端 DDL CHECK 约束保证范围。 */
  pct: number | null;
  sample_size: number | null;
  as_of: string | null;
}

/** key 形如 `long_short_ratio:30`、`basis_pct:90`。 */
export type CryptoFuturesPercentiles = Record<string, CryptoFuturesPercentile>;

export interface CryptoFuturesContract {
  contract_code: string;
  base_asset: string;
  /** 按 24h quoteVolume 倒序的 1..30 排名。 */
  oi_notional_rank: number | null;
  captured_at: string | null;
  mark_price: number | null;
  index_price: number | null;
  oi_contracts: number | null;
  /** 名义未平仓 = oi_contracts × mark_price（USDT）。 */
  oi_notional: number | null;
  long_short_ratio: number | null;
  taker_buy_sell_ratio: number | null;
  /** (mark_price - index_price) / index_price × 100。 */
  basis_pct: number | null;
  percentiles: CryptoFuturesPercentiles;
}

export interface CryptoFuturesSeriesPoint {
  captured_at: string;
  mark_price: number | null;
  oi_notional: number | null;
  long_short_ratio: number | null;
  taker_buy_sell_ratio: number | null;
  basis_pct: number | null;
}
