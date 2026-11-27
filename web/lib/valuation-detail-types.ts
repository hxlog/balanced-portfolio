/**
 * `/valuation/[code]` 指数详情页的前端类型。
 *
 * 单位约定沿用 `valuation-types.ts`：
 * - `pct` 为 0~100 百分数（与 DB/API 一致），展示层直接加 `%`。
 * - 股息率 / 风险溢价 / ROE 为「百分数点」，展示层不再 ×100。
 * - 成分股权重 `weight` 为 0~100 百分数点。
 * - 跟踪基金 `aum` 为元；展示层统一除以 1e8 转「亿元」。
 * - `null` 表示缺失或样本不足（<120），不得用 0 填充。
 */

import type { IndexCategory, ValuationLevel } from "./valuation-types";

/** 最新生效日的成分股。 */
export interface DetailConstituent {
  stock_code: string;
  name: string;
  industry_l1: string | null;
  /** 权重（百分数点，0~100）。 */
  weight: number | null;
  rank: number | null;
  effective_date: string | null;
}

/** 最新交易日的跟踪基金。 */
export interface DetailTrackerFund {
  fund_code: string;
  name: string;
  company_name: string | null;
  risk_grade: string | null;
  /** 规模（元）；展示层除以 1e8 转亿元。 */
  aum: number | null;
  trade_date: string | null;
  /** 基金经理。 */
  manager: string | null;
  /** 基金类型。 */
  fund_type: string | null;
  /** 管理费率（%/年）。 */
  management_fee: number | null;
  /** 托管费率（%/年）。 */
  custody_fee: number | null;
  /** 成立日期。 */
  established_date: string | null;
  /** 最新基金规模（元）。 */
  fund_scale: number | null;
  /** 各期收益（百分数点）。 */
  ret_1m: number | null;
  ret_3m: number | null;
  ret_6m: number | null;
  ret_12m: number | null;
  ret_2y: number | null;
  ret_3y: number | null;
  ret_5y: number | null;
  ytd: number | null;
  ann_vol_1y: number | null;
  max_dd_1y: number | null;
  tracking_error_1y: number | null;
  info_ratio_1y: number | null;
  risk_ret_3y_ann: number | null;
  risk_ret_5y_ann: number | null;
  /**
   * 该指数跟踪基金风险指标（TE/波动/回撤）的更新批次时间；后端字段缺失时为 null。
   * 注意：后端不返回「单只基金风险指标净值截止日」，故不设 risk_as_of 死字段。
   */
  risk_updated_at: string | null;
}

/** 分位窗口统计（详情 `percentiles[]` 与 history `stats` 共用）。 */
export interface PercentileSummary {
  /** 当前值在窗口内的分位，0~100；样本不足时为 null。 */
  pct: number | null;
  mean: number | null;
  sd: number | null;
  p20: number | null;
  p50: number | null;
  p80: number | null;
  min: number | null;
  max: number | null;
  /** 有效样本数（不含 null）。 */
  sample_size: number;
  /** 后端样本不足时给 `insufficient_sample`。 */
  reason?: string | null;
}

/** 详情接口 `percentiles` 数组的一行。 */
export interface DetailPercentile extends PercentileSummary {
  metric: string;
  window_key: string;
}

/** 详情接口映射后的完整快照。 */
export interface ValuationDetailData {
  index_code: string;
  name: string;
  market: string | null;
  index_type: IndexCategory;
  publisher: string | null;
  base_date: string | null;
  base_point: number | null;
  income_method: string | null;
  weight_method: string | null;
  intro: string | null;
  trade_date: string | null;
  /** 申万一级行业（宽基为 null）。 */
  industry: string | null;
  /** 最新收盘点位。 */
  close: number | null;
  /** 当日涨跌幅（百分数点）。 */
  change_pct: number | null;
  pe_ttm: number | null;
  pb: number | null;
  /** 股息率 TTM（百分数点）。 */
  dividend_yield_ttm: number | null;
  /** 风险溢价（百分数点）。 */
  erp: number | null;
  /** ROE TTM（百分数点）。 */
  roe_ttm: number | null;
  /** 十年期国债到期收益率（百分数点）。 */
  bond10y: number | null;
  level_pe: ValuationLevel | null;
  level_pb: ValuationLevel | null;
  level_dividend: ValuationLevel | null;
  constituents: DetailConstituent[];
  tracker_funds: DetailTrackerFund[];
  percentiles: DetailPercentile[];
  /** 区间收益风险（1y/3y/5y/all），后端从行情计算。 */
  risk: Partial<Record<"1y" | "3y" | "5y" | "all", DetailRiskStats>>;
  /** 跟踪基金快照的截至交易日（max(trade_date)）；无基金时为 null。 */
  tracker_funds_as_of: string | null;
  /** 跟踪基金 / 基金风险指标的计算更新时间（后端 updated_at）；缺失为 null。 */
  tracker_funds_updated_at: string | null;
  /** 指数点位历史（双轴主图用，bfq、原币）；后端未提供时为空数组。 */
  price_series: ValuationPricePoint[];
}

/** 指数点位历史点（原币、不复权）。 */
export interface ValuationPricePoint {
  trade_date: string;
  close: number;
}

/** 单个区间的收益风险统计（百分数点口径）。 */
export interface DetailRiskStats {
  total_return_pct: number | null;
  annualized_return_pct: number | null;
  volatility_pct: number | null;
  max_drawdown_pct: number | null;
  sharpe: number | null;
  sample_size: number;
}

/** history 接口的一个序列点。 */
export interface ValuationHistoryPoint {
  trade_date: string;
  /** 指标值（PE/PB 为倍数，股息率/ERP 为百分数点）。 */
  value: number;
}

/** history 接口映射后的数据。 */
export interface ValuationHistoryData {
  series: ValuationHistoryPoint[];
  stats: PercentileSummary | null;
}
