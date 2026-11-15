/**
 * /valuation 指数估值域的前端类型。
 *
 * 单位约定（与 docs/index-valuation/06-data-model-v3.md 对齐）：
 * - `*_pct` 均为「百分数点」：`-0.68` 表示 -0.68%，展示层不再 ×100。
 * - `pe_percentile` / `pb_percentile` 为 0~100 百分数（与 DB/API 一致），展示层直接加 `%`。
 * - `null` 表示缺失或样本不足（<120），不得用 0 填充；展示层统一显示「—」。
 * - `trade_date` / `as_of` / `captured_at` 均为 ISO 8601 字符串。
 *
 * 这些类型同时服务于首页、后续详情页与 API 响应映射，字段命名保持 snake_case，
 * 尽量与后端 JSON 同名；聚合卡片里的 `pe` / `pb` 是展示层字段，由 API 映射层
 * 从 `pe_median` / `pb_median` 显式取值，不在组件里猜口径。
 */

/** 指数类别，对应 bp_index_master.index_type。 */
export type IndexCategory = "宽基" | "行业" | "主题" | "策略" | "其他";

/** 估值等级，对应 bp_index_valuation_daily.level_*。 */
export type ValuationLevel = "低估" | "中性" | "高估";

/** 分位窗口，对应 bp_index_percentile.window_key。 */
export type PercentileWindow = "1y" | "3y" | "5y" | "10y" | "all";

/** 全市场板块，对应 bp_market_valuation_daily.board。 */
export type MarketBoard = "all" | "main" | "chinext" | "star" | "bse";

/** 参与分位计算的指标。 */
export type ValuationMetric =
  | "pe_ttm"
  | "pb"
  | "dividend_yield_ttm"
  | "erp";

/**
 * 单一指标在一个窗口内的分位统计。
 *
 * `pct` 为 0~100 百分数（与 DB/API 一致）；`sample_size` 是有效样本数（缺失值不计入），
 * 小于 120 时后端应把 `pct` 等统计量置 null，前端显示「样本不足」。
 */
export interface PercentileStats {
  metric: ValuationMetric;
  window_key: PercentileWindow;
  /** 当前值在窗口内的分位，0~100；样本不足时为 null。 */
  pct: number | null;
  /** 窗口均值。 */
  mean: number | null;
  /** 样本标准差（STDEV.S）；样本 <2 时为 null。 */
  sd: number | null;
  /** 20% / 50% / 80% 分位点。 */
  p20: number | null;
  p50: number | null;
  p80: number | null;
  min: number | null;
  max: number | null;
  /** 有效样本数（不含 null）。 */
  sample_size: number;
}

/**
 * 首页表格的一行：行情 + 最新估值快照。
 *
 * 行情与估值可能来自不同数据源；`has_valuation=false` 时估值字段必须全部为 null，
 * 仅展示行情列，前端标注「仅行情」。`has_etf` 表示当前是否有跟踪 ETF。
 */
export interface IndexQuoteRow {
  index_code: string;
  name: string;
  category: IndexCategory;
  publisher: string | null;
  /** 指数所属市场（CSI/SH/SZ/CNI/HK/US/BJ/GLOBAL）。 */
  market?: string | null;
  has_etf: boolean;
  has_valuation: boolean;
  /** 行情/估值的共同截止交易日。 */
  trade_date: string;
  /** 收盘点位。 */
  close: number | null;
  /** 当日涨跌幅（百分数点）。 */
  change_pct: number | null;
  /** 近 7 日涨跌幅（百分数点）；接口未提供时为 null。 */
  change_7d_pct?: number | null;
  /** 近 52 周涨跌幅（百分数点）。 */
  change_52w_pct: number | null;
  /** 距历史最高点的跌幅（百分数点，通常为负）。 */
  distance_from_high_pct: number | null;
  /** 52 周最高（收盘价口径）。 */
  high_52w?: number | null;
  /** 52 周最低（收盘价口径）。 */
  low_52w?: number | null;
  /** 当前收盘在 52 周高低区间中的位置，0~100。 */
  position_52w_pct?: number | null;
  /** 市盈率 TTM。 */
  pe_ttm: number | null;
  /** PE 历史分位，0~100（与 DB/API 同口径）。 */
  pe_percentile: number | null;
  /** 市净率。 */
  pb: number | null;
  /** PB 历史分位，0~100（与 DB/API 同口径）。 */
  pb_percentile: number | null;
  /** 股息率 TTM（百分数点）。 */
  dividend_yield_pct: number | null;
  /** 风险溢价 = 股息率 TTM − 十年期国债收益率（百分数点）。 */
  risk_premium_pct: number | null;
  /** 后端给出的 PE 估值等级。 */
  level_pe?: ValuationLevel | null;
  /** 后端给出的 PB 估值等级。 */
  level_pb?: ValuationLevel | null;
  /** 后端给出的股息率估值等级。 */
  level_dividend?: ValuationLevel | null;
  /** 申万一级行业（宽基为 null）。 */
  industry?: string | null;
  /** 股息率分位（所选窗口），0~100。 */
  dividend_percentile?: number | null;
  /** ERP 分位（所选窗口），0~100。 */
  erp_percentile?: number | null;
  /** 所选指标（metric）对应的分位，0~100。 */
  metric_percentile?: number | null;
  /** 数据区间内最高收盘（不是真正「历史最高」，页面上须注明区间）。 */
  high_all?: number | null;
  /** 距区间最高点的跌幅（百分数点，通常为负）。 */
  distance_from_all_high_pct?: number | null;
  /** ROE(TTM)，百分数点。 */
  roe_ttm?: number | null;
  /** 跟踪基金规模合计（元）。 */
  fund_aum?: number | null;
  /** 跟踪基金数量。 */
  fund_count?: number | null;
}

/** 估值历史序列点（bp_index_valuation_series）。 */
export interface HistoryPoint {
  trade_date: string;
  value: number;
}

/** 单指标单窗口的估值历史 + 区间统计。 */
export interface ValuationHistory {
  code: string;
  metric: ValuationMetric;
  window: PercentileWindow;
  series: HistoryPoint[];
  stats: PercentileStats | null;
}

/** 首页代表性宽基估值卡（真实历史分位）。 */
export interface BroadProxyCard {
  index_code: string;
  name: string;
  industry: string | null;
  trade_date: string;
  pe: number | null;
  pe_percentile: number | null;
  pb: number | null;
  pb_percentile: number | null;
  dividend_yield_pct: number | null;
  risk_premium_pct: number | null;
  window: PercentileWindow;
}

/**
 * 首页「全市场估值」的一张板块卡。
 *
 * `pe` / `pb` 为板块等权中位数；`history_days` 用于展示「历史归档积累中」，
 * 当 `pe_percentile` 为 null 时前端不显示百分比。
 */
export interface MarketValuationCard {
  board: MarketBoard;
  label: string;
  pe: number | null;
  /** PE 分位，0~100（与 DB/API 同口径）。 */
  pe_percentile: number | null;
  pb: number | null;
  /** PB 分位，0~100（与 DB/API 同口径）。 */
  pb_percentile: number | null;
  level: ValuationLevel | null;
  /** 数据截止日。 */
  as_of: string;
  /** 参与计算的股票数。 */
  sample_size: number;
  /** 已积累的历史交易日数。 */
  history_days: number;
}

/**
 * 详情页所需的完整估值快照。
 *
 * 首页不消费该类型；先落类型是为了后续 `/valuation/[code]` 与 API 映射共用同一契约，
 * 避免详情页再定义一套字段。各 `*_stats` 为对应指标在默认窗口（近 5 年）的统计。
 */
export interface ValuationDetail {
  index_code: string;
  name: string;
  category: IndexCategory;
  publisher: string | null;
  trade_date: string;
  close: number | null;
  change_pct: number | null;
  pe_ttm: number | null;
  pb: number | null;
  /** 股息率 TTM（百分数点）。 */
  dividend_yield_pct: number | null;
  /** 风险溢价（百分数点）。 */
  risk_premium_pct: number | null;
  /** 十年期国债到期收益率（百分数点）。 */
  bond10y_pct: number | null;
  /** ROE TTM（百分数点）。 */
  roe_ttm: number | null;
  level: ValuationLevel | null;
  pe_stats: PercentileStats | null;
  pb_stats: PercentileStats | null;
  dividend_stats: PercentileStats | null;
  erp_stats: PercentileStats | null;
  /** 跟踪 ETF 代码（可能为空数组，表示无 ETF）。 */
  tracker_etf_codes: string[];
  /** 主口径数据源（如 pingan_index）。 */
  source: string;
  /** 抓取/入库时间，PiT 审计用。 */
  captured_at: string;
}
