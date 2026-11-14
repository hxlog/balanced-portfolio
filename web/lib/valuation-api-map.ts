/** 后端 /api/valuation/* 响应 -> 前端类型映射（唯一入口，字段口径在这里收口）。 */
import type {
  IndexCategory,
  IndexQuoteRow,
  MarketBoard,
  MarketValuationCard,
  ValuationLevel,
} from "./valuation-types";

const CATEGORIES: ReadonlySet<string> = new Set(["宽基", "行业", "主题", "策略", "其他"]);
const LEVELS: ReadonlySet<string> = new Set(["低估", "中性", "高估"]);
const BOARDS: ReadonlySet<string> = new Set(["all", "main", "chinext", "star", "bse"]);
const BOARD_LABEL: Record<MarketBoard, string> = {
  all: "全市场",
  main: "主板",
  chinext: "创业板",
  star: "科创板",
  bse: "北交所",
};

function num(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) return Number(value);
  return null;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

function asCategory(value: unknown): IndexCategory {
  const text = typeof value === "string" ? value : "";
  return (CATEGORIES.has(text) ? text : "其他") as IndexCategory;
}

function asLevel(value: unknown): ValuationLevel | null {
  const text = typeof value === "string" ? value : "";
  return (LEVELS.has(text) ? text : null) as ValuationLevel | null;
}

export function mapIndexRow(raw: Record<string, unknown>): IndexQuoteRow {
  return {
    index_code: String(raw.index_code ?? ""),
    name: String(raw.name ?? ""),
    category: asCategory(raw.index_type),
    publisher: str(raw.publisher),
    market: str(raw.market),
    has_etf: Boolean(raw.has_etf),
    has_valuation: Boolean(raw.has_valuation),
    trade_date: String(raw.trade_date ?? ""),
    close: num(raw.close_price),
    change_pct: num(raw.change_pct),
    // 后端当前只提供当日涨跌；若后续补充 7 日字段则优先使用，不改契约。
    change_7d_pct:
      num(raw.change_7d_pct) ?? num(raw.change_7d) ?? num(raw.change_7d_pct_5),
    change_52w_pct: null,
    distance_from_high_pct: num(raw.dist_from_high_pct),
    high_52w: num(raw.high_52w),
    low_52w: num(raw.low_52w),
    position_52w_pct: num(raw.position_52w_pct),
    pe_ttm: num(raw.pe_ttm),
    pe_percentile: num(raw.pe_percentile),
    pb: num(raw.pb),
    pb_percentile: num(raw.pb_percentile),
    dividend_yield_pct: num(raw.dividend_yield_ttm),
    risk_premium_pct: num(raw.erp),
    level_pe: asLevel(raw.level_pe),
    level_pb: asLevel(raw.level_pb),
    level_dividend: asLevel(raw.level_dividend),
  };
}

export function mapMarketCard(raw: Record<string, unknown>): MarketValuationCard {
  const boardText = typeof raw.board === "string" ? raw.board : "";
  const board = (BOARDS.has(boardText) ? boardText : "all") as MarketBoard;
  return {
    board,
    label: BOARD_LABEL[board],
    pe: num(raw.pe_median) ?? num(raw.pe),
    pe_percentile: num(raw.pct_pe) ?? num(raw.pe_percentile),
    pb: num(raw.pb_median) ?? num(raw.pb),
    pb_percentile: num(raw.pct_pb) ?? num(raw.pb_percentile),
    level: asLevel(raw.level),
    as_of: String(raw.trade_date ?? raw.as_of ?? ""),
    sample_size: num(raw.sample_size) ?? 0,
    history_days: num(raw.history_days) ?? 0,
  };
}
