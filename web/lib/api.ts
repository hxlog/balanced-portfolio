// Balanced Portfolio - 前端 API 客户端
// 通过 Next rewrites 代理到后端 (/api -> http://localhost:8000)

export type Quadrant = "overheat" | "stagflation" | "recovery" | "recession";

export const QUADRANT_LABELS: Record<Quadrant, string> = {
  overheat: "过热 (通胀↑ 增长↑)",
  stagflation: "滞胀 (通胀↑ 增长↓)",
  recovery: "复苏 (通胀↓ 增长↑)",
  recession: "衰退 (通胀↓ 增长↓)",
};

export const METHOD_OPTIONS = [
  {
    value: "quadrant_inner_sharpe_outer_rp",
    title: "象限内最大化优化指标，象限间风险平价",
    desc: "默认推荐。先在每个象限内最大化当前所选优化指标（夏普或 Sortino），再让各象限波动率贡献相等（ERC），两层权重相乘得到最终配置。",
  },
  {
    value: "all_risk_parity",
    title: "所有投资品之间风险平价",
    desc: "经典风险平价。让每一个基础资产对总组合的波动率贡献完全相等。",
  },
  {
    value: "all_max_sharpe",
    title: "全体最大化优化指标",
    desc: "马科维茨均值方差框架下，纯粹追求组合历史优化指标（夏普或 Sortino）最大化。",
  },
  {
    value: "sharpe_sq_risk_budget",
    title: "按优化指标²分配风险",
    desc: "动量与风险的折中：各资产风险预算 ∝ 单资产优化指标²，给予历史表现更优的资产更高风险预算。",
  },
];

/** 优化方法短名（与优化指标 sharpe/sortino 无关的通用表述） */
export const METHOD_LABELS: Record<string, string> = {
  quadrant_inner_sharpe_outer_rp: "象限内最大化优化指标·象限间平价",
  all_risk_parity: "全体风险平价",
  all_max_sharpe: "全体最大化优化指标",
  sharpe_sq_risk_budget: "按优化指标²分配风险",
};

export function methodLabel(method: string): string {
  return METHOD_LABELS[method] ?? method;
}

// 候选基准(与后端 BENCHMARKS 注册表一致)
export const BENCHMARK_OPTIONS = [
  { key: "bond6040", name: "60/40经典股债" },
  { key: "000300", name: "沪深300" },
  { key: "000510", name: "中证A500" },
  { key: "000905", name: "中证500" },
  { key: "HSI", name: "恒生指数" },
];

/** 多腿合成基准的构成说明(与后端 BENCHMARKS 注册表一致) */
export const BENCHMARK_COMPOSITION: Record<string, { legs: { weight: number; name: string }[]; note: string }> = {
  bond6040: {
    legs: [
      { weight: 0.6, name: "中债-国债总财富全价指数 (10Y)" },
      { weight: 0.4, name: "沪深300" },
    ],
    note: "两成分按固定权重每日再平衡，合成基准净值用于与组合对比。",
  },
};

export const DEFAULT_BENCHMARK_KEY = "bond6040";
export const DEFAULT_MAX_WEIGHT = 1 / 3;
export const DEFAULT_MAX_WEIGHT_PCT = +(DEFAULT_MAX_WEIGHT * 100).toFixed(2);
export const DEFAULT_DESCRIPTION = "组合描述";

// ==========================================================================
// 场外衍生品定价 (OTC)
// ==========================================================================
export type OtcProductType = "snowball" | "phoenix" | "airbag" | "barrier";

export const OTC_PRODUCTS: { value: OtcProductType; label: string; desc: string }[] = [
  { value: "snowball", label: "雪球 Snowball", desc: "含敲入敲出的自动赎回结构; 敲出得票息, 敲入承担下行, 未触碰得红利票息。" },
  { value: "phoenix", label: "凤凰 Phoenix", desc: "派息障碍之上逐期派息, 敲出提前终止, 敲入到期承担下行。" },
  { value: "airbag", label: "气囊 Airbag", desc: "下方设保护障碍, 未敲入享上行参与, 敲入后线性承担下行。" },
  { value: "barrier", label: "障碍 Barrier", desc: "单边障碍期权: 上/下 × 敲入/敲出 × 看涨/看跌。" },
];

export const OTC_ENGINES: Record<OtcProductType, { value: string; label: string }[]> = {
  snowball: [{ value: "mc", label: "Monte Carlo" }],
  phoenix: [{ value: "mc", label: "Monte Carlo" }],
  airbag: [
    { value: "mc", label: "Monte Carlo" },
    { value: "analytic", label: "闭式解 (BSM解析)" },
    { value: "quad", label: "积分法 (数值积分)" },
  ],
  barrier: [
    { value: "analytic", label: "闭式解 (BSM解析)" },
    { value: "quad", label: "积分法 (数值积分)" },
    { value: "mc", label: "Monte Carlo" },
  ],
};

export const OTC_VOL_QUICK = [
  { symbol: "000852", label: "中证1000" },
  { symbol: "000905", label: "中证500" },
  { symbol: "000300", label: "沪深300" },
  { symbol: "000016", label: "上证50" },
  { symbol: "HSI", label: "恒生指数" },
] as const;

export const OTC_DAYCOUNTS = [
  { value: "ACT365", label: "ACT/365", hint: "自然日/365 — 票息计息默认" },
  { value: "ACT360", label: "ACT/360", hint: "自然日/360 — 货币市场惯例" },
  { value: "BUS252", label: "Bus/252", hint: "交易日/252 — 折现与年化波动率口径" },
];

export const OTC_VOL_WINDOWS = [90, 120, 180, 365];

export const OTC_STATUS_LABELS: Record<string, string> = {
  alive: "存续中", knocked_in: "已敲入(存续)", knocked_out: "已敲出(终止)", expired: "已到期",
};

export interface OtcUnderlying { symbol: string; source: string; name: string | null; asset_class?: string | null; }
export interface OtcCalendarDay { date: string; is_trading: boolean; confidence: "official" | "estimated" | "custom"; }
export interface OtcObservationDate { requested: string; effective: string | null; rolled: boolean; }
export interface OtcGreeks { delta?: number; gamma?: number; vega?: number; theta?: number; rho?: number; }
export interface OtcChart {
  dates: string[];
  underlying: (number | null)[];
  forward_mean: (number | null)[];
  mean_path?: (number | null)[];
  ko_line: number | null;
  ki_line: number | null;
  baseline_line?: (number | null)[];
  lock_area: [string, string] | null;
  lock_end?: string | null;
  ko_observation_dates?: string[];
  events: { type: string; date: string; level: number; terminated?: boolean }[];
  s0: number;
  valuation_date: string;
  pnl?: (number | null)[];
  pnl_start?: number;
}
export interface OtcPriceResult {
  price: number;
  present_notional: number;
  status: string;
  greeks: OtcGreeks;
  chart: OtcChart;
  meta: Record<string, unknown>;
  current_pnl?: number;
}
export interface OtcVolPoint { date: string; vol: number; }
export interface OtcVolSeries { symbol: string; source: string; name: string | null; windows: Record<string, OtcVolPoint[]>; }
export interface OtcDeal {
  deal_id: number;
  name: string;
  product_type: OtcProductType;
  engine: string;
  underlying_symbol: string;
  underlying_source: string;
  terms: OtcPriceInput;
  is_example: boolean;
  owner_user_id: number | null;
  last_price: number | null;
  last_present_notional: number | null;
  last_greeks: OtcGreeks | null;
  last_status: string | null;
  last_valued_at: string | null;
  last_result?: OtcPriceResult | null;
  created_at: string;
  updated_at: string;
}
export interface OtcTaskStatus {
  task_id: string;
  status: "queued" | "running" | "success" | "failed" | "cancelled";
  progress_current: number;
  progress_total: number;
  progress_message: string | null;
  result: OtcPriceResult | Record<string, never>;
  error: string | null;
}
export interface OtcPriceInput {
  product_type: OtcProductType;
  direction: "buy" | "sell";
  engine: string;
  underlying_symbol: string;
  underlying_source: string;
  start_date: string;
  maturity_date: string;
  valuation_date?: string | null;
  s0: number;
  spot?: number | null;
  r: number;
  q: number;
  vol: number;
  notional: number;
  day_count: string;
  t_step_per_year?: number;
  n_paths?: number;
  seed?: number;
  greeks?: boolean;
  // snowball / phoenix
  ko_barrier_pct?: number | null;
  ki_barrier_pct?: number | null;
  ki_strike_pct?: number | null;
  coupon_out?: number | null;
  coupon_div?: number | null;
  ko_freq_months?: number;
  lock_term_months?: number;
  ko_observation_dates?: string[] | null;
  already_ki?: boolean;
  coupon_barrier_pct?: number | null;
  period_coupon?: number | null;
  // airbag
  strike_pct?: number | null;
  barrier_pct?: number | null;
  knockin_parti?: number | null;
  call_parti?: number | null;
  reset_call_parti?: number | null;
  // barrier
  rebate?: number | null;
  parti?: number | null;
  updown?: string | null;
  inout?: string | null;
  callput?: string | null;
  discrete_obs?: boolean;
}

/** 投资品类别(与后端 bp_index_config.category 一致) */
export const ASSET_CATEGORY_OPTIONS = [
  { value: "index", label: "指数" },
  { value: "etf", label: "ETF" },
  { value: "commodity", label: "商品" },
  { value: "bond", label: "债券" },
] as const;

export const ASSET_CATEGORY_LABELS: Record<string, string> = Object.fromEntries(
  ASSET_CATEGORY_OPTIONS.map((o) => [o.value, o.label]),
);

/** 复权类型(与后端 bp_index_config.extra_params.adjust 一致; 仅 ETF 有) */
export const ASSET_ADJUST_OPTIONS = [
  { value: "bfq", label: "不复权" },
  { value: "qfq", label: "前复权" },
  { value: "hfq", label: "后复权" },
] as const;

export const ADJUST_LABEL: Record<string, string> = Object.fromEntries(
  ASSET_ADJUST_OPTIONS.map((o) => [o.value, o.label]),
);

export interface Asset {
  symbol: string;
  source: string;
  category?: string;
  name?: string;
  asset_class?: string;
  vendor?: string;   // 数据供应商中文短名(东财/新浪/腾讯/中金所/中债)
  adjust?: string;   // 复权: bfq/qfq/hfq(仅 ETF; 缺省视为不复权)
}

export interface NavPoint {
  trade_date: string;
  nav: number;
  benchmark_nav?: number | null;
  ret?: number | null;
  bench_ret?: number | null;
}

export interface Rebalance {
  trade_date: string;
  reason?: string;
  target_weights: Record<string, number>;
  prev_weights?: Record<string, number> | null;
  delta?: Record<string, number> | null;
  quadrant_weights?: Record<string, number> | null;
  max_deviation?: number | null;
}

export interface Holding {
  key: string;
  symbol?: string;
  source?: string;
  name?: string;
  quadrant?: Quadrant;
  quadrants?: Quadrant[];
  weight: number;
}

export interface Metrics {
  annualized_return: number;
  annualized_vol: number;
  sharpe: number;
  sortino: number;
  calmar: number;
  max_drawdown: number;
  max_drawdown_recovery_days?: number | null;
  information_ratio?: number | null;
  total_return: number;
  start_date: string;
  end_date: string;
  period_returns: Record<string, number | null>;
  period_vols: Record<string, number | null>;
}

export interface PortfolioInfo {
  portfolio_id: number;
  name: string;
  description?: string;
  method: string;
  ratio: string;
  lookback_days?: number;
  start_date: string;
  effective_start_date?: string | null;
  benchmark_key?: string;
  benchmark_name?: string;
  rebalance_band?: number;
  max_weight?: number | null;
  is_demo: boolean;
  owner_user_id?: number | null;
  risk_free_rate?: number;
  fee_rate?: number;
  slippage_rate?: number;
  stamp_duty_rate?: number;
  result_version?: number;
  result_updated_at?: string | null;
  data_as_of_date?: string | null;
  status: string;
  error?: string | null;
  assets?: Array<{ symbol: string; source: string; quadrant: Quadrant; display_name?: string }>;
}

export interface AttributionAsset {
  key: string;
  name: string;
  quadrants: Quadrant[];
  avg_weight: number;
  asset_return: number;
  contribution: number;
  static: number;
  timing: number;
}

export interface AttributionRebalance {
  trade_date: string;
  end_date: string;
  reason?: string | null;
  period_return: number;
  contribution: number;
}

export interface Attribution {
  summary: {
    total_return: number;
    beta: number;
    systematic: number;
    selection: number;
    timing: number;
    residual: number;
  };
  assets: AttributionAsset[];
  rebalances: AttributionRebalance[];
}

export interface MethodSummary {
  method: string;
  total_return?: number | null;
  annualized_return?: number | null;
  sharpe?: number | null;
  is_default: boolean;
  is_best_total_return: boolean;
}

export interface BacktestResult {
  portfolio: PortfolioInfo;
  nav: NavPoint[];
  rebalances: Rebalance[];
  metrics: { portfolio?: Metrics; benchmark?: Metrics };
  holdings: Holding[];
  /** 末交易日滚动最优目标权重(与最近一次再平衡日可能不同) */
  optimal_holdings?: {
    as_of_date: string;
    holdings: Holding[];
    quadrant_weights?: Record<string, number> | null;
  } | null;
  quadrant_weights?: Record<string, number> | null;
  corr: { labels: string[]; matrix: number[][]; cov?: number[][] };
  attribution?: Attribution | null;
  method?: string;
  available_methods?: string[];
  method_summaries?: MethodSummary[];
  benchmark?: string;
  benchmark_name?: string;
  benchmarks?: Array<{ key: string; name: string }>;
}

export interface CreatePortfolioInput {
  name: string;
  description: string;
  method: string;
  ratio: string;
  lookback_days: number;
  start_date: string;
  benchmark_key: string;
  max_weight: number;
  rebalance_band: number;
  risk_free_rate?: number | null;
  fee_rate: number;
  slippage_rate: number;
  stamp_duty_rate: number;
  assets: Array<{ symbol: string; source: string; quadrant: Quadrant; display_name?: string }>;
}

export interface CreatePortfolioResponse {
  portfolio_id: number;
  status: string;
  task_id?: string;
}

export interface PortfolioStatus {
  portfolio_id: number;
  status: string;
  error?: string | null;
  effective_start_date?: string | null;
  active_task?: TaskStatus | null;
}

export interface TaskStatus {
  task_id: string;
  task_type: string;
  status: "queued" | "running" | "success" | "failed" | "cancelled";
  portfolio_id?: number | null;
  progress_current: number;
  progress_total: number;
  progress_message?: string | null;
  result?: Record<string, unknown>;
  error?: string | null;
}

export interface AuthProfile {
  user_id?: number | null;
  email: string;
  /** 任意已登录白名单用户(可创建/编辑自己的组合) */
  is_whitelisted: boolean;
  /** 真实管理员(可见全部组合、管理用户/资产/示例) */
  is_super_admin: boolean;
  role?: "user" | "admin";
  /** 是否已绑定 TOTP 两步验证 */
  totp_enabled: boolean;
  /** 管理员尚未绑定 TOTP 时为 true，前端需强制其绑定 */
  must_setup_2fa: boolean;
}

export interface AdminUser {
  email: string;
  created_at: string | null;
  is_super_admin: boolean;
  role?: string;
  status?: string;
  portfolio_count?: number;
  portfolio_limit?: number | null;
}

export interface DataSource {
  code: string;
  description: string;
  asset_class: string;
  symbol_hint?: string | null;
  supports_date_range: boolean;
  is_enabled: boolean;
  vendor?: string | null;
}

export interface AdminAsset {
  symbol: string;
  source: string;
  category?: string | null;
  name?: string | null;
  start_date?: string | null;
  is_deleted: number;
  is_selectable?: boolean;
  asset_class?: string | null;
  vendor?: string | null;
  adjust?: string | null;
  last_raw_date?: string | null;
  last_clean_date?: string | null;
  raw_rows: number;
  clean_rows: number;
  last_success_at?: string | null;
  last_error?: string | null;
  last_probe_ms?: number | null;
}

const TOKEN_KEY = "bp_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

function tokenExpiresInHours(token: string): number | null {
  try {
    const payload = JSON.parse(atob(token.split(".")[1])) as { exp?: number };
    if (!payload.exp) return null;
    return (payload.exp * 1000 - Date.now()) / (3600 * 1000);
  } catch {
    return null;
  }
}

export function shouldRefreshToken(token: string | null): boolean {
  if (!token) return false;
  const hours = tokenExpiresInHours(token);
  return hours !== null && hours < 48;
}

async function sessionFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* noop */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

let refreshInFlight: Promise<string | null> | null = null;

async function refreshSessionToken(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      const token = getToken();
      const data = await sessionFetch<{ token?: string }>("/api/session/refresh", {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (data.token) {
        setToken(data.token);
        return data.token;
      }
      return null;
    } catch {
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

async function req<T>(path: string, init?: RequestInit, retried = false): Promise<T> {
  const token = getToken();
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
  });
  if (res.status === 401 && !retried && path !== "/api/auth/login") {
    const newToken = await refreshSessionToken();
    if (newToken) return req<T>(path, init, true);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* noop */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

function q(params: Record<string, string | undefined>): string {
  const s = Object.entries(params)
    .filter(([, v]) => v)
    .map(([k, v]) => `${k}=${encodeURIComponent(v as string)}`)
    .join("&");
  return s ? `?${s}` : "";
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export const api = {
  getAssets: () => req<{ assets: Asset[] }>("/api/assets"),
  listPortfolios: () => req<{ portfolios: PortfolioInfo[] }>("/api/portfolios"),
  getDemo: (portfolioId?: number, method?: string, benchmark?: string) =>
    req<BacktestResult>(
      `/api/portfolios/demo${q({
        portfolio_id: portfolioId != null ? String(portfolioId) : undefined,
        method,
        benchmark,
      })}`,
    ),
  getResult: (id: number, method?: string, benchmark?: string) =>
    req<BacktestResult>(`/api/portfolios/${id}/result${q({ method, benchmark })}`),
  getPortfolioStatus: (id: number) =>
    req<PortfolioStatus>(`/api/portfolios/${id}/status`),
  getPortfolio: (id: number) =>
    req<PortfolioInfo>(`/api/portfolios/${id}`),
  createPortfolio: (input: CreatePortfolioInput) =>
    req<CreatePortfolioResponse>("/api/portfolios", { method: "POST", body: JSON.stringify(input) }),
  updatePortfolio: (id: number, input: CreatePortfolioInput) =>
    req<CreatePortfolioResponse>(`/api/portfolios/${id}`, { method: "PUT", body: JSON.stringify(input) }),
  updatePortfolioMeta: (id: number, input: { name: string; description: string }) =>
    req<{ portfolio_id: number }>(`/api/portfolios/${id}/meta`, {
      method: "PATCH", body: JSON.stringify(input),
    }),
  /** 轮询直到回测 done; error 时抛错 */
  waitForPortfolio: async (
    id: number,
    opts?: { intervalMs?: number; onPoll?: (st: PortfolioStatus) => void },
  ) => {
    const interval = opts?.intervalMs ?? 2000;
    for (;;) {
      const st = await api.getPortfolioStatus(id);
      opts?.onPoll?.(st);
      if (st.status === "done") return st;
      if (st.status === "error") throw new Error(st.error || "回测失败");
      await sleep(interval);
    }
  },
  getTask: (taskId: string) => req<TaskStatus>(`/api/tasks/${taskId}`),
  waitForTask: async (
    taskId: string,
    opts?: {
      intervalMs?: number;
      onPoll?: (st: TaskStatus) => void;
      onTransientError?: (e: unknown, count: number) => void;
      maxTransientErrors?: number;
    },
  ) => {
    const interval = opts?.intervalMs ?? 2000;
    const maxTransientErrors = opts?.maxTransientErrors ?? Number.POSITIVE_INFINITY;
    let transientErrors = 0;
    for (;;) {
      try {
        const st = await api.getTask(taskId);
        transientErrors = 0;
        opts?.onPoll?.(st);
        if (st.status === "success") return st;
        if (st.status === "failed" || st.status === "cancelled") {
          throw Object.assign(new Error(st.error || "任务失败"), { terminalTask: true });
        }
      } catch (e) {
        if (!(e as { terminalTask?: boolean }).terminalTask) {
          transientErrors += 1;
          opts?.onTransientError?.(e, transientErrors);
          if (transientErrors > maxTransientErrors) throw e;
        } else {
          throw e;
        }
      }
      await sleep(interval);
    }
  },
  deletePortfolio: (id: number) =>
    req<{ ok: boolean }>(`/api/portfolios/${id}`, { method: "DELETE" }),
  reorderPortfolios: (orderedIds: number[]) =>
    req<{ ok: boolean }>("/api/portfolios/order", {
      method: "PATCH",
      body: JSON.stringify({ ordered_ids: orderedIds }),
    }),
  recomputePortfolio: (id: number) =>
    req<CreatePortfolioResponse>(`/api/portfolios/${id}/recompute`, { method: "POST" }),
  copyPortfolio: (id: number, name?: string) =>
    req<CreatePortfolioResponse>(`/api/portfolios/${id}/copy`, {
      method: "POST", body: JSON.stringify({ name: name ?? null }),
    }),
  setDemoFlag: (id: number, is_demo: boolean) =>
    req<{ portfolio_id: number; is_demo: boolean }>(`/api/portfolios/${id}/demo`, {
      method: "PATCH",
      body: JSON.stringify({ is_demo }),
    }),
  // -------------------- 场外衍生品 (OTC) --------------------
  otcUnderlyings: () => req<{ underlyings: OtcUnderlying[] }>("/api/otc/underlyings"),
  otcCalendar: (dfrom: string, dto: string) =>
    req<{ market: string; days: OtcCalendarDay[] }>(`/api/otc/calendar${q({ dfrom, dto })}`),
  otcObservationDates: (input: {
    start_date: string; maturity_date: string; dates?: string[]; freq_months?: number; lock_term_months?: number;
  }) =>
    req<{ dates: OtcObservationDate[] }>("/api/otc/observation-dates", {
      method: "POST", body: JSON.stringify(input),
    }),
  otcVolatility: (symbols: string[], windows: number[], source?: string) =>
    req<{ series: Record<string, OtcVolSeries> }>(
      `/api/otc/volatility${q({ symbols: symbols.join(","), windows: windows.join(","), source })}`,
    ),
  otcVolSuggest: (symbol: string, window = 90, source?: string) =>
    req<{ symbol: string; source: string | null; window: number; vol: number | null }>(
      `/api/otc/vol-suggest${q({ symbol, window: String(window), source })}`,
    ),
  otcSpot: (symbol: string, source?: string, onDate?: string) =>
    req<{ symbol: string; source: string; date: string; close: number }>(
      `/api/otc/spot${q({ symbol, source, date: onDate })}`,
    ),
  otcPrice: (input: OtcPriceInput, dealId?: number) =>
    req<{ task_id: string }>(`/api/otc/price${dealId != null ? q({ deal_id: String(dealId) }) : ""}`, {
      method: "POST", body: JSON.stringify(input),
    }),
  otcTask: (taskId: string) => req<OtcTaskStatus>(`/api/otc/tasks/${taskId}`),
  otcWaitTask: async (
    taskId: string,
    opts?: { intervalMs?: number; onPoll?: (st: OtcTaskStatus) => void },
  ): Promise<OtcPriceResult> => {
    const interval = opts?.intervalMs ?? 1200;
    for (;;) {
      const st = await api.otcTask(taskId);
      opts?.onPoll?.(st);
      if (st.status === "success") return st.result as OtcPriceResult;
      if (st.status === "failed" || st.status === "cancelled") {
        throw new Error(st.error || "定价失败");
      }
      await sleep(interval);
    }
  },
  otcListDeals: () => req<{ deals: OtcDeal[] }>("/api/otc/deals"),
  otcReorderDeals: (orderedIds: number[]) =>
    req<{ ok: boolean }>("/api/otc/deals/order", {
      method: "PATCH",
      body: JSON.stringify({ ordered_ids: orderedIds }),
    }),
  otcGetDeal: (id: number) => req<OtcDeal>(`/api/otc/deals/${id}`),
  otcCreateDeal: (name: string, params: OtcPriceInput) =>
    req<{ deal_id: number; task_id: string }>("/api/otc/deals", { method: "POST", body: JSON.stringify({ name, params }) }),
  otcUpdateDeal: (id: number, name: string, params: OtcPriceInput) =>
    req<{ deal_id: number; ok: boolean }>(`/api/otc/deals/${id}`, {
      method: "PUT", body: JSON.stringify({ name, params }),
    }),
  otcDeleteDeal: (id: number) => req<{ ok: boolean }>(`/api/otc/deals/${id}`, { method: "DELETE" }),
  otcSetExample: (id: number, is_example: boolean) =>
    req<{ deal_id: number; is_example: boolean }>(`/api/otc/deals/${id}/example`, {
      method: "PATCH", body: JSON.stringify({ is_example }),
    }),
  otcRepriceDeal: (id: number) =>
    req<{ task_id: string }>(`/api/otc/deals/${id}/reprice`, { method: "POST" }),

  me: () => req<AuthProfile>("/api/auth/me"),
  listUsers: () => req<{ users: AdminUser[] }>("/api/admin/users"),
  createUser: (email: string, password: string) =>
    req<{ ok: boolean }>("/api/admin/users", {
      method: "POST", body: JSON.stringify({ email, password }),
    }),
  deleteUser: (email: string) =>
    req<{ ok: boolean }>(`/api/admin/users/${encodeURIComponent(email)}`, { method: "DELETE" }),
  updateUser: (email: string, input: { portfolio_limit?: number | null; status?: string }) =>
    req<{ ok: boolean; email: string; portfolio_limit: number }>(
      `/api/admin/users/${encodeURIComponent(email)}`,
      {
        method: "PATCH",
        body: JSON.stringify(input),
      },
    ),
  login: (email: string, password: string, otp_code?: string) =>
    sessionFetch<{ token?: string; email: string; requires_2fa?: boolean }>("/api/session", {
      method: "POST",
      body: JSON.stringify({ email, password, otp_code }),
    }),
  restoreSession: () =>
    sessionFetch<AuthProfile & { token?: string }>("/api/session"),
  logoutSession: () =>
    sessionFetch<{ ok: boolean }>("/api/session", { method: "DELETE" }),
  refreshSession: () => {
    const token = getToken();
    return sessionFetch<{ token: string; email: string }>("/api/session/refresh", {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  },
  changePassword: (old_password: string, new_password: string) =>
    req<{ ok: boolean }>("/api/auth/change-password", {
      method: "POST", body: JSON.stringify({ old_password, new_password }),
    }),
  setup2fa: (currentCode?: string) =>
    req<{ secret: string; otpauth_url: string }>("/api/auth/2fa/setup", {
      method: "POST",
      body: JSON.stringify({ current_code: currentCode ?? null }),
    }),
  verify2fa: (code: string) =>
    req<{ ok: boolean }>("/api/auth/2fa/verify", {
      method: "POST", body: JSON.stringify({ code }),
    }),
  disable2fa: (code: string) =>
    req<{ ok: boolean }>("/api/auth/2fa/disable", {
      method: "POST", body: JSON.stringify({ code }),
    }),
  listDataSources: () => req<{ data_sources: DataSource[] }>("/api/admin/data-sources"),
  listAdminAssets: () => req<{ assets: AdminAsset[] }>("/api/admin/assets"),
  refreshAdminAssetStatus: () =>
    req<{ ok: boolean }>("/api/admin/assets/refresh-status", { method: "POST" }),
  syncAllAssets: () =>
    req<{ task_id: string; status: string }>("/api/admin/assets/sync-all", { method: "POST" }),
  enqueueReadyPortfolios: () =>
    req<{ queued: number; portfolios: Array<{ portfolio_id: number; task_id: string; target_trade_date: string }> }>(
      "/api/admin/portfolios/enqueue-ready",
      { method: "POST" },
    ),
  saveAdminAsset: (input: {
    symbol: string; source: string; name: string; category?: string | null; start_date?: string | null; is_deleted?: number; adjust?: string | null;
  }) => req<{ ok: boolean }>("/api/admin/assets", { method: "POST", body: JSON.stringify(input) }),
  deleteAdminAsset: (source: string, symbol: string) =>
    req<{ ok: boolean }>(`/api/admin/assets/${encodeURIComponent(source)}/${encodeURIComponent(symbol)}`, { method: "DELETE" }),
  probeAdminAsset: (source: string, symbol: string) =>
    req<{ ok: boolean; rows: number; first_date?: string; last_date?: string; elapsed_ms: number }>(
      `/api/admin/assets/${encodeURIComponent(source)}/${encodeURIComponent(symbol)}/probe`,
      { method: "POST" },
    ),
  syncAdminAsset: (source: string, symbol: string) =>
    req<{ ok: boolean; status: string; rows: number; detail: string }>(
      `/api/admin/assets/${encodeURIComponent(source)}/${encodeURIComponent(symbol)}/sync`,
      { method: "POST" },
    ),
  setAssetSelectable: (source: string, symbol: string, selectable: boolean) =>
    req<{ ok: boolean; selectable: boolean }>(
      `/api/admin/assets/${encodeURIComponent(source)}/${encodeURIComponent(symbol)}/selectable`,
      { method: "PATCH", body: JSON.stringify({ selectable }) },
    ),
};
