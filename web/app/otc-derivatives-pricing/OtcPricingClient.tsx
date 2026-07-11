"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTheme } from "next-themes";
import {
  Activity, Bookmark, Calculator, HelpCircle, LineChart, Loader2, RefreshCw, Search, Star, Trash2, TrendingUp, Lock,
  Check, ChevronsUpDown, ArrowUpDown, ArrowUp, ArrowDown, CalendarIcon,
} from "lucide-react";
import {
  api,
  OTC_PRODUCTS, OTC_ENGINES, OTC_DAYCOUNTS, OTC_VOL_WINDOWS, OTC_VOL_QUICK, OTC_STATUS_LABELS,
  type OtcProductType, type OtcPriceInput, type OtcPriceResult, type OtcUnderlying,
  type OtcDeal, type OtcObservationDate, type OtcVolSeries, type OtcTaskStatus,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { EChart } from "@/components/EChart";
import { MiniTradingCalendar } from "@/components/MiniTradingCalendar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Progress } from "@/components/ui/progress";
import { Calendar } from "@/components/ui/calendar";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList,
} from "@/components/ui/command";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { cn } from "@/components/ui/utils";

const INPUT_BG = "bg-background";

type Form = Record<string, string | boolean>;

function parseThousand(v: string | boolean | undefined): number {
  if (typeof v === "boolean") return 0;
  const s = String(v ?? "").replace(/,/g, "").trim();
  return s === "" ? 0 : Number(s);
}

function formatThousand(v: string | boolean | undefined): string {
  const n = parseThousand(v);
  if (!Number.isFinite(n) || n === 0) return String(v ?? "");
  return n.toLocaleString("en-US");
}

/** ISO YYYY-MM-DD → YYYY/MM/DD 展示 */
function isoToSlash(iso: string): string {
  if (!iso) return "";
  return iso.replace(/-/g, "/");
}

/** Date → ISO YYYY-MM-DD */
function toIsoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** 解析 YYYY/MM/DD 或 YYYY-MM-DD → ISO; 非法返回 null */
function parseSlashOrIsoDate(raw: string): string | null {
  const s = raw.trim().replace(/\//g, "-");
  const m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(s);
  if (!m) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return null;
  const dt = new Date(y, mo - 1, d);
  if (dt.getFullYear() !== y || dt.getMonth() !== mo - 1 || dt.getDate() !== d) return null;
  return toIsoDate(dt);
}

/** 估值日默认: min(today, maturity), 且 >= start */
function defaultValuationDate(start: string, maturity: string): string {
  const today = toIsoDate(new Date());
  let vd = today <= maturity ? today : maturity;
  if (start && vd < start) vd = start;
  return vd;
}

const PRODUCT_BARRIER_DEFAULT: Record<OtcProductType, string> = {
  snowball: "70", phoenix: "70", airbag: "70", barrier: "110",
};

function n(v: string | boolean | undefined): number {
  return typeof v === "string" ? Number(v) : Number(v);
}

function fmtMoney(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(x)) return "—";
  return x.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

function fmtMoney2(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(x)) return "—";
  return x.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function statusBadgeClass(status: string | null): string {
  switch (status) {
    case "knocked_out": return "bg-down/10 text-down border-down/20";
    case "knocked_in": return "bg-up/10 text-up border-up/20";
    case "expired": return "bg-muted text-muted-foreground border-border";
    default: return "bg-primary/10 text-primary border-primary/20";
  }
}

const DEFAULTS: Form = {
  product_type: "snowball",
  direction: "buy",
  engine: "mc",
  underlying_symbol: "000852",
  underlying_source: "cn_index_em",
  start_date: "2021-03-15",
  maturity_date: "2022-03-15",
  valuation_date: defaultValuationDate("2021-03-15", "2022-03-15"),
  s0: "6000",
  spot: "",
  r: "2",
  q: "0.5",
  vol: "35",
  notional: "10,000,000",
  day_count: "ACT365",
  n_paths: "500,000",
  // snowball / phoenix (% of initial)
  ko_barrier: "103",
  ki_barrier: "75",
  ki_strike: "80",
  coupon_out: "20",
  coupon_div: "10",
  ko_freq_months: "1",
  lock_term_months: "0",
  already_ki: false,
  coupon_barrier: "75",
  period_coupon: "0.76",
  // airbag / barrier
  strike: "100",
  barrier_lvl: "70",
  knockin_parti: "1",
  call_parti: "0.7",
  reset_call_parti: "1",
  rebate: "0",
  parti: "1",
  updown: "up",
  inout: "out",
  callput: "call",
  discrete_obs: true,
};

export function OtcPricingClient() {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const { isWhitelisted, isSuperAdmin, userId, ready } = useAuth();

  const [f, setF] = useState<Form>(DEFAULTS);
  const product = f.product_type as OtcProductType;
  const set = useCallback((k: string, v: string | boolean) => setF((p) => ({ ...p, [k]: v })), []);

  const [underlyings, setUnderlyings] = useState<OtcUnderlying[]>([]);
  const [obsDates, setObsDates] = useState<OtcObservationDate[]>([]);
  const [result, setResult] = useState<OtcPriceResult | null>(null);
  const [pricing, setPricing] = useState(false);
  const [progress, setProgress] = useState<{ cur: number; total: number; msg: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [currentDealId, setCurrentDealId] = useState<number | null>(null);
  const [valInitKey, setValInitKey] = useState("");
  const canPrice = isWhitelisted;

  useEffect(() => {
    api.otcUnderlyings().then((r) => setUnderlyings(r.underlyings)).catch(() => {});
  }, []);

  // 挂载/切标的/切日期 → 估值日默认 min(today, maturity) + 自动初始点位
  useEffect(() => {
    const sym = f.underlying_symbol as string;
    const src = f.underlying_source as string;
    const start = f.start_date as string;
    const maturity = f.maturity_date as string;
    if (!sym || !start || !maturity) return;
    const key = `${sym}|${start}|${maturity}`;
    if (key === valInitKey) return;
    setValInitKey(key);
    set("valuation_date", defaultValuationDate(start, maturity));
    api.otcSpot(sym, src, start)
      .then((r) => set("s0", String(r.close)))
      .catch(() => {});
  }, [f.underlying_symbol, f.underlying_source, f.start_date, f.maturity_date, valInitKey, set]);

  // 挂钩标的变化 → 建议成交波动率(近90交易日历史波动率)
  useEffect(() => {
    const sym = f.underlying_symbol as string;
    if (!sym) return;
    let cancelled = false;
    api.otcVolSuggest(sym, 90, f.underlying_source as string)
      .then((r) => {
        if (cancelled || r.vol == null) return;
        set("vol", String(+(r.vol * 100).toFixed(1)));
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [f.underlying_symbol, f.underlying_source, set]);

  // 敲出观察日预览(雪球/凤凰)
  useEffect(() => {
    if (product !== "snowball" && product !== "phoenix") { setObsDates([]); return; }
    const start = f.start_date as string;
    const maturity = f.maturity_date as string;
    if (!start || !maturity) return;
    let cancelled = false;
    api.otcObservationDates({
      start_date: start, maturity_date: maturity,
      freq_months: n(f.ko_freq_months), lock_term_months: n(f.lock_term_months),
    })
      .then((r) => !cancelled && setObsDates(r.dates))
      .catch(() => !cancelled && setObsDates([]));
    return () => { cancelled = true; };
  }, [product, f.start_date, f.maturity_date, f.ko_freq_months, f.lock_term_months]);

  const koEffectiveDates = useMemo(
    () => obsDates.map((d) => d.effective).filter((x): x is string => !!x),
    [obsDates],
  );

  function switchProduct(p: OtcProductType) {
    setF((prev) => ({
      ...prev,
      product_type: p,
      engine: OTC_ENGINES[p][0].value,
      barrier_lvl: PRODUCT_BARRIER_DEFAULT[p],
    }));
    setResult(null);
    setCurrentDealId(null);
  }

  // -------------------- 构建 payload --------------------
  const buildPayload = useCallback((): OtcPriceInput => {
    const common = {
      product_type: product,
      direction: f.direction as "buy" | "sell",
      engine: f.engine as string,
      underlying_symbol: f.underlying_symbol as string,
      underlying_source: f.underlying_source as string,
      start_date: f.start_date as string,
      maturity_date: f.maturity_date as string,
      valuation_date: (f.valuation_date as string) || null,
      s0: n(f.s0),
      spot: f.spot === "" ? null : n(f.spot),
      r: n(f.r) / 100,
      q: n(f.q) / 100,
      vol: n(f.vol) / 100,
      notional: parseThousand(f.notional),
      day_count: f.day_count as string,
      t_step_per_year: 252,
      n_paths: parseThousand(f.n_paths),
      seed: 42,
      greeks: true,
    };
    if (product === "snowball") {
      return {
        ...common,
        ko_barrier_pct: n(f.ko_barrier), ki_barrier_pct: n(f.ki_barrier), ki_strike_pct: n(f.ki_strike),
        coupon_out: n(f.coupon_out) / 100, coupon_div: n(f.coupon_div) / 100,
        ko_freq_months: 1, lock_term_months: n(f.lock_term_months),
        already_ki: f.already_ki as boolean,
      };
    }
    if (product === "phoenix") {
      return {
        ...common,
        ko_barrier_pct: n(f.ko_barrier), ki_barrier_pct: n(f.ki_barrier), ki_strike_pct: n(f.ki_strike),
        coupon_barrier_pct: n(f.coupon_barrier), period_coupon: n(f.period_coupon) / 100,
        ko_freq_months: 1, lock_term_months: n(f.lock_term_months),
        already_ki: f.already_ki as boolean,
      };
    }
    if (product === "airbag") {
      return {
        ...common,
        strike_pct: n(f.strike), barrier_pct: n(f.barrier_lvl),
        knockin_parti: n(f.knockin_parti), call_parti: n(f.call_parti), reset_call_parti: n(f.reset_call_parti),
        discrete_obs: f.discrete_obs as boolean,
      };
    }
    return {
      ...common,
      strike_pct: n(f.strike), barrier_pct: n(f.barrier_lvl),
      rebate: (n(f.s0) * n(f.rebate)) / 100, parti: n(f.parti),
      updown: f.updown as string, inout: f.inout as string, callput: f.callput as string,
      discrete_obs: f.discrete_obs as boolean,
    };
  }, [f, product]);

  // -------------------- 定价 --------------------
  const runPricing = useCallback(async () => {
    if (!canPrice) {
      setError("请登录后使用定价功能");
      return;
    }
    setError(null); setNotice(null); setPricing(true); setProgress({ cur: 0, total: 7, msg: "排队中" });
    try {
      const { task_id } = await api.otcPrice(buildPayload(), currentDealId ?? undefined);
      const res = await api.otcWaitTask(task_id, {
        onPoll: (st: OtcTaskStatus) =>
          setProgress({ cur: st.progress_current, total: st.progress_total || 7, msg: st.progress_message || "" }),
      });
      setResult(res);
      if (currentDealId) api.otcListDeals().then((r) => setDeals(r.deals)).catch(() => {});
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPricing(false); setProgress(null);
    }
  }, [buildPayload, canPrice, currentDealId]);

  // -------------------- 簿记 --------------------
  const [deals, setDeals] = useState<OtcDeal[]>([]);
  const [dealName, setDealName] = useState("");
  const [dealFilterProduct, setDealFilterProduct] = useState<string>("all");
  const [dealFilterSymbol, setDealFilterSymbol] = useState("");
  const [dealSortKey, setDealSortKey] = useState<"product" | "symbol" | "notional" | "pnl" | null>(null);
  const [dealSortDir, setDealSortDir] = useState<"asc" | "desc">("asc");
  const [anonAutoLoaded, setAnonAutoLoaded] = useState(false);

  const toggleDealSort = useCallback((key: "product" | "symbol" | "notional" | "pnl") => {
    setDealSortKey((prev) => {
      if (prev === key) {
        setDealSortDir((d) => (d === "asc" ? "desc" : "asc"));
        return key;
      }
      setDealSortDir("asc");
      return key;
    });
  }, []);

  const filteredDeals = useMemo(() => {
    let list = deals;
    if (dealFilterProduct !== "all") {
      list = list.filter((d) => d.product_type === dealFilterProduct);
    }
    if (dealFilterSymbol.trim()) {
      const q = dealFilterSymbol.trim().toLowerCase();
      list = list.filter((d) =>
        d.underlying_symbol.toLowerCase().includes(q)
        || (d.name || "").toLowerCase().includes(q),
      );
    }
    if (dealSortKey) {
      const dir = dealSortDir === "asc" ? 1 : -1;
      list = [...list].sort((a, b) => {
        if (dealSortKey === "product") return a.product_type.localeCompare(b.product_type) * dir;
        if (dealSortKey === "symbol") return a.underlying_symbol.localeCompare(b.underlying_symbol) * dir;
        if (dealSortKey === "notional") {
          const an = Number(a.terms?.notional ?? 0);
          const bn = Number(b.terms?.notional ?? 0);
          return (an - bn) * dir;
        }
        const ap = a.last_result?.current_pnl ?? Number.NEGATIVE_INFINITY;
        const bp = b.last_result?.current_pnl ?? Number.NEGATIVE_INFINITY;
        return (ap - bp) * dir;
      });
    }
    return list;
  }, [deals, dealFilterProduct, dealFilterSymbol, dealSortKey, dealSortDir]);

  const SortIcon = ({ k }: { k: "product" | "symbol" | "notional" | "pnl" }) => {
    if (dealSortKey !== k) return <ArrowUpDown className="w-3 h-3 ml-1 opacity-40" />;
    return dealSortDir === "asc"
      ? <ArrowUp className="w-3 h-3 ml-1" />
      : <ArrowDown className="w-3 h-3 ml-1" />;
  };

  const loadDeals = useCallback(() => {
    api.otcListDeals().then((r) => setDeals(r.deals)).catch(() => {});
  }, []);
  useEffect(() => { if (ready) loadDeals(); }, [ready, loadDeals]);

  // 匿名用户: 默认载入示例列表第一条的上次定价结果
  useEffect(() => {
    if (!ready || isWhitelisted || anonAutoLoaded || deals.length === 0) return;
    if (result != null || currentDealId != null) {
      setAnonAutoLoaded(true);
      return;
    }
    const first = deals.find((d) => d.is_example) ?? deals[0];
    if (first?.last_result) {
      setResult(first.last_result);
      setNotice(`示例「${first.name}」只读结果`);
    }
    setAnonAutoLoaded(true);
  }, [ready, isWhitelisted, anonAutoLoaded, deals, result, currentDealId]);

  const saveDeal = useCallback(async () => {
    if (!canPrice) { setError("请登录后存为簿记"); return; }
    setError(null);
    try {
      const name = dealName.trim() || `${OTC_PRODUCTS.find((p) => p.value === product)?.label ?? product} @ ${f.underlying_symbol}`;
      if (currentDealId != null) {
        await api.otcUpdateDeal(currentDealId, name, buildPayload());
        setDealName(name);
        setNotice(`已保存簿记「${name}」参数`);
        loadDeals();
        return;
      }
      const { deal_id, task_id } = await api.otcCreateDeal(name, buildPayload());
      setDealName(name);
      setCurrentDealId(deal_id);
      setNotice("已存入簿记, 正在重估…");
      const res = await api.otcWaitTask(task_id);
      setResult(res);
      loadDeals();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [canPrice, dealName, product, f.underlying_symbol, buildPayload, loadDeals, currentDealId]);

  const loadDealIntoForm = useCallback(async (deal: OtcDeal) => {
    // 优先走单条 GET(Redis 缓存), 失败则用列表里的 last_result
    let full = deal;
    try {
      full = await api.otcGetDeal(deal.deal_id);
    } catch {
      /* keep list payload */
    }
    const t = full.terms || ({} as OtcPriceInput);
    setF((prev) => ({
      ...prev,
      product_type: full.product_type,
      engine: full.engine,
      direction: t.direction ?? "buy",
      underlying_symbol: full.underlying_symbol,
      underlying_source: full.underlying_source,
      start_date: t.start_date ?? prev.start_date,
      maturity_date: t.maturity_date ?? prev.maturity_date,
      valuation_date: t.valuation_date
        || defaultValuationDate(t.start_date ?? (prev.start_date as string), t.maturity_date ?? (prev.maturity_date as string)),
      s0: String(t.s0 ?? prev.s0),
      spot: t.spot != null ? String(t.spot) : "",
      r: String(((t.r ?? 0.02) * 100)),
      q: String(((t.q ?? 0) * 100)),
      vol: String(((t.vol ?? 0.3) * 100)),
      notional: String(t.notional ?? prev.notional),
      day_count: t.day_count ?? "ACT365",
      n_paths: String(t.n_paths ?? 100000),
      ko_barrier: String(t.ko_barrier_pct ?? prev.ko_barrier),
      ki_barrier: String(t.ki_barrier_pct ?? prev.ki_barrier),
      ki_strike: String(t.ki_strike_pct ?? prev.ki_strike),
      coupon_out: String(((t.coupon_out ?? 0.2) * 100)),
      coupon_div: String(((t.coupon_div ?? 0.1) * 100)),
      ko_freq_months: String(t.ko_freq_months ?? 1),
      lock_term_months: String(t.lock_term_months ?? 0),
      already_ki: t.already_ki ?? false,
      coupon_barrier: String(t.coupon_barrier_pct ?? prev.coupon_barrier),
      period_coupon: String(((t.period_coupon ?? 0.0076) * 100)),
      strike: String(t.strike_pct ?? prev.strike),
      barrier_lvl: String(t.barrier_pct ?? PRODUCT_BARRIER_DEFAULT[full.product_type]),
      knockin_parti: String(t.knockin_parti ?? 1),
      call_parti: String(t.call_parti ?? 0.7),
      reset_call_parti: String(t.reset_call_parti ?? 1),
      parti: String(t.parti ?? 1),
      updown: t.updown ?? "up",
      inout: t.inout ?? "out",
      callput: t.callput ?? "call",
      discrete_obs: t.discrete_obs ?? true,
    }));
    setDealName(full.name);
    setCurrentDealId(full.deal_id);
    if (full.last_result) {
      setResult(full.last_result);
      setNotice(`已载入簿记「${full.name}」及上次定价结果`);
    } else {
      setResult(null);
      setNotice(`已载入簿记「${full.name}」到参数区`);
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const [repricingId, setRepricingId] = useState<number | null>(null);
  const repriceDeal = useCallback(async (deal: OtcDeal) => {
    setRepricingId(deal.deal_id);
    try {
      const { task_id } = await api.otcRepriceDeal(deal.deal_id);
      await api.otcWaitTask(task_id);
      loadDeals();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRepricingId(null);
    }
  }, [loadDeals]);

  const deleteDeal = useCallback(async (deal: OtcDeal) => {
    if (!confirm(`删除簿记「${deal.name}」?`)) return;
    try { await api.otcDeleteDeal(deal.deal_id); loadDeals(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }, [loadDeals]);

  const viewExampleResult = useCallback((deal: OtcDeal) => {
    if (deal.last_result) {
      setResult(deal.last_result);
      setNotice(`示例「${deal.name}」只读结果`);
      window.scrollTo({ top: 400, behavior: "smooth" });
    } else {
      setNotice(`示例「${deal.name}」暂无估值结果`);
    }
  }, []);

  const toggleExample = useCallback(async (deal: OtcDeal) => {
    try { await api.otcSetExample(deal.deal_id, !deal.is_example); loadDeals(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }, [loadDeals]);

  // -------------------- 图表配色 --------------------
  const chartColors = useMemo(() => ({
    text: isDark ? "#A1A1A1" : "#666666",
    axis: isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)",
    split: isDark ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)",
    cardBg: isDark ? "#161616" : "#ffffff",
    fg: isDark ? "#EDEDED" : "#171717",
  }), [isDark]);

  // -------------------- 示意图 option --------------------
  const pathOption = useMemo(() => {
    if (!result) return null;
    const c = result.chart;
    const dateSet = new Set(c.dates);
    const firstDate = c.dates[0];
    const lastDate = c.dates[c.dates.length - 1];
    // 敲出线自锁定期结束后起画 (锁定期内不画敲出线; 敲入线始终全程)
    const koStart = (c.lock_end && dateSet.has(c.lock_end))
      ? c.lock_end
      : (c.lock_end && c.dates.find((d) => d >= c.lock_end!) ) || firstDate;

    const fmtLvlInt = (v: number) => Math.round(v).toLocaleString("zh-CN");
    const pctOfS0 = (lvl: number) => `${Math.round((lvl / c.s0) * 100)}%`;
    const barrierLabel = (prefix: string, lvl: number) =>
      `${prefix} ${pctOfS0(lvl)} · ${fmtLvlInt(lvl)}`;
    const labelStyle = (color: string) => ({
      color,
      fontSize: 10,
      overflow: "break" as const,
      width: 168,
      distance: 6,
      show: true,
    });

    // 左轴必须同时覆盖挂钩指数 + 基准 + 敲入 + 敲出 (禁止只缩放到指数局部)
    const indexVals = (c.underlying || []).filter((v): v is number => v != null && Number.isFinite(v));
    const levels: number[] = [c.s0];
    if (c.ki_line != null) levels.push(c.ki_line);
    if (c.ko_line != null) levels.push(c.ko_line);
    const allY = [...indexVals, ...levels];
    let yMin: number | undefined;
    let yMax: number | undefined;
    if (allY.length > 0) {
      const lo = Math.min(...allY);
      const hi = Math.max(...allY);
      const span = Math.max(hi - lo, Math.abs(c.s0) * 0.05, 100);
      const pad = Math.max(span * 0.08, 80);
      yMin = Math.floor(lo - pad);
      yMax = Math.ceil(hi + pad);
    }

    const markLineData: unknown[] = [];
    if (c.baseline_line?.length) {
      markLineData.push({
        yAxis: c.s0, name: "100%基准",
        lineStyle: { type: "solid", color: "#94a3b8", width: 1 },
        label: { ...labelStyle(chartColors.text), formatter: `100% · ${fmtLvlInt(c.s0)}` },
      });
    }
    // 敲入线: 全程水平
    if (c.ki_line != null) {
      markLineData.push({
        yAxis: c.ki_line, name: "敲入线",
        lineStyle: { type: "dashed", color: "#ef4444", width: 1.5 },
        label: { ...labelStyle("#ef4444"), formatter: barrierLabel("敲入", c.ki_line) },
      });
    }
    // 敲出线: 锁定期后水平线段 (观察日之间上穿不算敲出)
    if (c.ko_line != null && koStart && lastDate && koStart <= lastDate) {
      markLineData.push([
        {
          coord: [koStart, c.ko_line],
          lineStyle: { type: "dashed", color: "#10b981", width: 1.5 },
          label: {
            ...labelStyle("#10b981"),
            formatter: barrierLabel("敲出", c.ko_line),
            position: "end",
          },
        },
        { coord: [lastDate, c.ko_line] },
      ]);
    }
    // 月度敲出观察日竖线 — 加粗不加深
    const koObs = (c.ko_observation_dates || []).filter((d) => dateSet.has(d));
    const koEventDate = (c.events || []).find((e) => e.type === "knock_out")?.date;
    for (const od of koObs) {
      const isTerm = od === koEventDate;
      markLineData.push({
        xAxis: od,
        name: isTerm ? "观察日·敲出" : "月观察日",
        lineStyle: {
          type: "dotted",
          color: isTerm ? "#10b981" : (isDark ? "rgba(148,163,184,0.45)" : "rgba(148,163,184,0.55)"),
          width: isTerm ? 3 : 2.5,
        },
        label: isTerm
          ? { formatter: "观察日·敲出", color: "#10b981", fontSize: 9, position: "insideEndTop" }
          : { show: false },
      });
    }

    const eventPoints = (c.events || [])
      .filter((e) => dateSet.has(e.date) && Number.isFinite(e.level))
      .map((e) => {
        const isIn = e.type.includes("in");
        const isExpired = e.type.includes("expir");
        const terminated = Boolean(e.terminated) || e.type.includes("out");
        const label = isIn ? "敲入" : isExpired ? "到期" : terminated ? "敲出·终止" : "敲出";
        return {
          name: label,
          coord: [e.date, e.level] as [string, number],
          symbol: "pin",
          symbolSize: 38,
          symbolOffset: isIn ? [0, 8] : [0, -8],
          itemStyle: { color: isIn ? "#ef4444" : isExpired ? "#94a3b8" : "#10b981" },
          label: { show: true, color: "#fff", fontSize: 9, formatter: label },
        };
      });

    // 双保险: 示意图末日盈亏 = 结果卡 current_pnl
    let pnlData = c.pnl ? [...c.pnl] : undefined;
    if (pnlData && pnlData.length > 0 && result.current_pnl != null && Number.isFinite(result.current_pnl)) {
      pnlData[pnlData.length - 1] = result.current_pnl;
    }

    const indexDisplay = (c.underlying || []).map((v) =>
      v == null || !Number.isFinite(v) ? null : Math.round(v),
    );

    const series: Record<string, unknown>[] = [
      {
        name: "挂钩指数(存续)", type: "line", yAxisIndex: 0, data: indexDisplay,
        showSymbol: false, smooth: true, connectNulls: false,
        itemStyle: { color: "#3B82F6" },
        lineStyle: { width: 2, color: "#3B82F6" },
        markLine: { symbol: "none", data: markLineData },
        markArea: c.lock_area ? {
          itemStyle: { color: isDark ? "rgba(234,179,8,0.12)" : "rgba(234,179,8,0.14)" },
          label: { show: true, color: chartColors.text, fontSize: 10, position: "top", formatter: "锁定期" },
          data: [[{ xAxis: c.lock_area[0] }, { xAxis: c.lock_area[1] }]],
        } : undefined,
        markPoint: eventPoints.length ? { data: eventPoints } : undefined,
      },
    ];
    if (pnlData?.some((v) => v != null)) {
      series.push({
        name: "盈亏", type: "line", yAxisIndex: 1, data: pnlData,
        showSymbol: false, smooth: true, connectNulls: true,
        itemStyle: { color: "#f59e0b" },
        lineStyle: { width: 2, color: "#f59e0b" },
      });
    }
    return {
      color: ["#3B82F6", "#f59e0b"],
      tooltip: {
        trigger: "axis", backgroundColor: chartColors.cardBg, borderColor: chartColors.axis,
        textStyle: { color: chartColors.fg, fontFamily: "monospace" }, axisPointer: { type: "cross" },
        formatter: (params: unknown) => {
          const rows = Array.isArray(params) ? params : [params];
          if (!rows.length) return "";
          const axisVal = (rows[0] as { axisValue?: string }).axisValue ?? "";
          const lines = [`${axisVal}`];
          for (const p of rows) {
            const item = p as { seriesName?: string; value?: number | null; marker?: string };
            const v = item.value;
            const formatted = item.seriesName === "盈亏"
              ? (v == null || !Number.isFinite(v) ? "—" : fmtMoney2(v))
              : (v == null || !Number.isFinite(v) ? "—" : Math.round(Number(v)).toLocaleString("zh-CN"));
            lines.push(`${item.marker ?? ""}${item.seriesName}: ${formatted}`);
          }
          return lines.join("<br/>");
        },
      },
      legend: {
        data: series.map((s) => s.name as string),
        textStyle: { color: chartColors.text }, top: 0,
      },
      grid: { top: 36, right: 56, bottom: 40, left: 80 },
      xAxis: {
        type: "category", data: c.dates, boundaryGap: false,
        axisLabel: { color: chartColors.text, fontSize: 10 },
        axisLine: { lineStyle: { color: chartColors.axis } },
      },
      yAxis: [
        {
          type: "value",
          scale: false,
          min: yMin,
          max: yMax,
          name: "指数点位",
          axisLabel: {
            color: chartColors.text,
            fontSize: 10,
            formatter: (v: number) => Math.round(v).toLocaleString("zh-CN"),
          },
          splitLine: { lineStyle: { color: chartColors.split } },
        },
        {
          type: "value", scale: true, name: "盈亏", axisLabel: { color: chartColors.text, fontSize: 10 },
          splitLine: { show: false },
        },
      ],
      // 仅横向缩放, 禁止纵向裁掉敲入/敲出线
      dataZoom: [
        { type: "inside", xAxisIndex: 0, filterMode: "none" },
        { type: "slider", xAxisIndex: 0, filterMode: "none", height: 16, bottom: 8 },
      ],
      series,
    };
  }, [result, chartColors, isDark]);

  // -------------------- 波动率 --------------------
  const [volSymbols, setVolSymbols] = useState<string[]>(["000905", "000852"]);
  const [volWindow, setVolWindow] = useState<number>(90);
  const [volRangeYears, setVolRangeYears] = useState<3 | 5>(3);
  const [volData, setVolData] = useState<Record<string, OtcVolSeries>>({});
  const [volLoading, setVolLoading] = useState(false);
  const [volPickerOpen, setVolPickerOpen] = useState(false);
  const [underlyingOpen, setUnderlyingOpen] = useState(false);

  useEffect(() => {
    if (volSymbols.length === 0) { setVolData({}); return; }
    let cancelled = false;
    setVolLoading(true);
    api.otcVolatility(volSymbols, OTC_VOL_WINDOWS)
      .then((r) => !cancelled && setVolData(r.series))
      .catch(() => !cancelled && setVolData({}))
      .finally(() => !cancelled && setVolLoading(false));
    return () => { cancelled = true; };
  }, [volSymbols]);

  const volOption = useMemo(() => {
    const symbols = Object.keys(volData);
    if (symbols.length === 0) return null;
    const dateSet = new Set<string>();
    for (const sym of symbols) {
      for (const p of volData[sym].windows[String(volWindow)] || []) dateSet.add(p.date);
    }
    let dates = Array.from(dateSet).sort();
    if (dates.length > 0) {
      const last = dates[dates.length - 1];
      const cutoff = new Date(last + "T00:00:00");
      cutoff.setFullYear(cutoff.getFullYear() - volRangeYears);
      const cutIso = toIsoDate(cutoff);
      dates = dates.filter((d) => d >= cutIso);
    }
    const idx = new Map(dates.map((d, i) => [d, i]));
    const palette = ["#3B82F6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16"];
    const series = symbols.map((sym, i) => {
      const arr: (number | null)[] = new Array(dates.length).fill(null);
      for (const p of volData[sym].windows[String(volWindow)] || []) {
        const j = idx.get(p.date);
        if (j != null) arr[j] = +(p.vol * 100).toFixed(2);
      }
      return {
        name: volData[sym].name || sym, type: "line", data: arr, showSymbol: false, smooth: true,
        connectNulls: true, lineStyle: { width: 1.5, color: palette[i % palette.length] },
        itemStyle: { color: palette[i % palette.length] },
      };
    });
    return {
      tooltip: {
        trigger: "axis", backgroundColor: chartColors.cardBg, borderColor: chartColors.axis,
        textStyle: { color: chartColors.fg, fontFamily: "monospace" },
        valueFormatter: (v: number) => (v == null ? "—" : `${v}%`),
      },
      legend: { textStyle: { color: chartColors.text }, top: 0, type: "scroll" },
      grid: { top: 36, right: 24, bottom: 44, left: 48 },
      xAxis: {
        type: "category", data: dates, axisLabel: { color: chartColors.text, fontSize: 10 },
        axisLine: { lineStyle: { color: chartColors.axis } },
      },
      yAxis: {
        type: "value", scale: true, axisLabel: { color: chartColors.text, fontSize: 10, formatter: "{value}%" },
        splitLine: { lineStyle: { color: chartColors.split } },
      },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 16, bottom: 10 }],
      series,
    };
  }, [volData, volWindow, volRangeYears, chartColors]);

  const indexUnderlyings = underlyings;

  // -------------------- 渲染 --------------------
  const showSnowballish = product === "snowball" || product === "phoenix";
  const s0Num = n(f.s0);
  const koLineLevel = Number.isFinite(s0Num) && s0Num > 0
    ? Math.round(s0Num * n(f.ko_barrier) / 100)
    : null;
  const kiLineLevel = Number.isFinite(s0Num) && s0Num > 0
    ? Math.round(s0Num * n(f.ki_barrier) / 100)
    : null;
  const fmtLvl = (v: number | null) =>
    v == null || !Number.isFinite(v) ? "—" : v.toLocaleString("zh-CN");

  return (
    <div className="flex-1 px-4 py-4 sm:p-6 max-w-7xl mx-auto w-full min-w-0 space-y-4 sm:space-y-6">
      {/* 顶部标题 + 迷你日历 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-card border border-border rounded-xl shadow-sm p-5 space-y-3">
          <div className="flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-primary" />
            <h1 className="text-xl font-semibold tracking-tight">场外衍生品定价</h1>
            <Badge variant="secondary" className="font-normal">Monte Carlo / 解析 · 全套 Greeks</Badge>
          </div>
          <p className="text-sm text-muted-foreground leading-relaxed">
            雪球 / 凤凰 / 气囊 / 障碍 场外结构化产品定价与簿记。品种与算法参考 pricelib，
            蒙特卡洛严格按 A股交易日历做日度敲入 / 月度敲出观测，红利票息按 ACT/365 计息、Bus/252 折现。
          </p>
          <div className="flex flex-wrap gap-2">
            {OTC_PRODUCTS.map((p) => (
              <button
                key={p.value}
                onClick={() => switchProduct(p.value)}
                className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${
                  product === p.value
                    ? "bg-primary text-primary-foreground border-primary"
                    : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/30"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <p className="text-xs text-muted-foreground/80">
            {OTC_PRODUCTS.find((p) => p.value === product)?.desc}
          </p>
        </div>
        <MiniTradingCalendar
          startDate={f.start_date as string}
          maturityDate={f.maturity_date as string}
          valuationDate={f.valuation_date as string}
        />
      </div>

      {/* 参数表单 */}
      <Card className="min-w-0">
        <CardHeader className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 space-y-0 border-b border-border/60 pb-4">
          <CardTitle className="text-base flex flex-wrap items-center gap-2">
            <Calculator className="w-4 h-4 text-primary" /> 参数设置
            {!canPrice && (
              <Badge variant="outline" className="font-normal text-xs">登录后可定价与簿记</Badge>
            )}
          </CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            {canPrice && (
              <>
                <Input
                  placeholder="簿记名称(可选)" value={dealName}
                  onChange={(e) => setDealName(e.target.value)} className={cn("w-full sm:w-40 h-9", INPUT_BG)}
                />
                <Button variant="outline" size="sm" onClick={saveDeal} disabled={pricing}>
                  <Bookmark className="w-4 h-4 mr-1" />
                  {currentDealId != null ? "保存参数" : "存为簿记"}
                </Button>
              </>
            )}
            <Button size="sm" onClick={runPricing} disabled={pricing || !canPrice} className="rounded-full px-5">
              {pricing ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Activity className="w-4 h-4 mr-1" />}
              生成定价
            </Button>
          </div>
        </CardHeader>
        <CardContent className={`p-5 space-y-5 ${!canPrice ? "opacity-60 pointer-events-none select-none" : ""}`}>
          {/* 通用 */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <FieldSelect label="交易方向" value={f.direction as string} onChange={(v) => set("direction", v)}
              options={[{ value: "buy", label: "买入" }, { value: "sell", label: "卖出" }]} />
            <FieldSelect label="算法" value={f.engine as string} onChange={(v) => set("engine", v)}
              options={OTC_ENGINES[product]} />
            <UnderlyingCombobox
              underlyings={indexUnderlyings}
              value={f.underlying_symbol as string}
              open={underlyingOpen}
              onOpenChange={setUnderlyingOpen}
              onChange={(sym, src) => setF((p) => ({ ...p, underlying_symbol: sym, underlying_source: src }))}
            />
            <Field label="名义本金 (元)"><ThousandInput value={f.notional} onChange={(v) => set("notional", v)} /></Field>

            <DateField label="初始观察日" value={f.start_date as string} onChange={(v) => set("start_date", v)} />
            <Field label="初始观察日点位" hint="自动读取起始日收盘">
              <Input readOnly value={f.s0 as string} className={cn("h-9 font-mono", INPUT_BG)} />
            </Field>
            <DateField label="到期观察日" value={f.maturity_date as string} onChange={(v) => set("maturity_date", v)} />
            <DateField label="估值日" value={f.valuation_date as string} onChange={(v) => set("valuation_date", v)} />

            <Field label="无风险利率" hint="年化 %"><NumInput value={f.r} onChange={(v) => set("r", v)} step="0.1" suffix="%" /></Field>
            <Field label="分红率 / 贴水" hint="年化 %"><NumInput value={f.q} onChange={(v) => set("q", v)} step="0.1" suffix="%" /></Field>
            <Field label="成交波动率" hint="默认近90交易日历史波动率, 可调"><NumInput value={f.vol} onChange={(v) => set("vol", v)} step="0.5" suffix="%" /></Field>
            <Field label="计息规则" hint={OTC_DAYCOUNTS.find((d) => d.value === f.day_count)?.hint}>
              <div className="flex items-center gap-1">
                <Select value={f.day_count as string} onValueChange={(v) => set("day_count", v)}>
                  <SelectTrigger className={cn("h-9 flex-1", INPUT_BG)}><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {OTC_DAYCOUNTS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
                  </SelectContent>
                </Select>
                <Popover>
                  <PopoverTrigger asChild>
                    <Button variant="ghost" size="icon" className="h-9 w-9 shrink-0" type="button"><HelpCircle className="w-4 h-4" /></Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-72 text-xs space-y-2">
                    {OTC_DAYCOUNTS.map((d) => (
                      <p key={d.value}><strong>{d.label}</strong> — {d.hint}</p>
                    ))}
                  </PopoverContent>
                </Popover>
              </div>
            </Field>
          </div>

          {/* 品种特有 */}
          <div className="border-t border-border/50 pt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {showSnowballish && (
              <>
                <Field label="敲出障碍" hint="% of 初始"><NumInput value={f.ko_barrier} onChange={(v) => set("ko_barrier", v)} step="1" suffix="%" /></Field>
                <Field label="敲出线" hint="初始点位 × 敲出障碍">
                  <Input readOnly value={fmtLvl(koLineLevel)} className={cn("h-9 font-mono tabular-nums text-muted-foreground", INPUT_BG)} />
                </Field>
                <Field label="敲入障碍" hint="% of 初始"><NumInput value={f.ki_barrier} onChange={(v) => set("ki_barrier", v)} step="1" suffix="%" /></Field>
                <Field label="敲入线" hint="初始点位 × 敲入障碍">
                  <Input readOnly value={fmtLvl(kiLineLevel)} className={cn("h-9 font-mono tabular-nums text-muted-foreground", INPUT_BG)} />
                </Field>
                <Field label="锁定期" hint="月, 期内不观敲出"><NumInput value={f.lock_term_months} onChange={(v) => set("lock_term_months", v)} step="1" /></Field>
              </>
            )}
            {product === "snowball" && (
              <>
                <Field label="敲出票息" hint="年化 %"><NumInput value={f.coupon_out} onChange={(v) => set("coupon_out", v)} step="0.5" suffix="%" /></Field>
                <Field label="红利/期末票息" hint="未敲出未敲入到期, 年化 %"><NumInput value={f.coupon_div} onChange={(v) => set("coupon_div", v)} step="0.5" suffix="%" /></Field>
                <Field label="敲入行权" hint="% of 初始"><NumInput value={f.ki_strike} onChange={(v) => set("ki_strike", v)} step="1" suffix="%" /></Field>
                <FieldSwitch label="是否已敲入" checked={f.already_ki as boolean} onChange={(v) => set("already_ki", v)} />
              </>
            )}
            {product === "phoenix" && (
              <>
                <Field label="派息障碍" hint="% of 初始"><NumInput value={f.coupon_barrier} onChange={(v) => set("coupon_barrier", v)} step="1" suffix="%" /></Field>
                <Field label="每期派息" hint="占名义 %"><NumInput value={f.period_coupon} onChange={(v) => set("period_coupon", v)} step="0.01" suffix="%" /></Field>
                <Field label="敲入行权" hint="% of 初始"><NumInput value={f.ki_strike} onChange={(v) => set("ki_strike", v)} step="1" suffix="%" /></Field>
                <FieldSwitch label="是否已敲入" checked={f.already_ki as boolean} onChange={(v) => set("already_ki", v)} />
              </>
            )}
            {product === "airbag" && (
              <>
                <Field label="行权价" hint="% of 初始"><NumInput value={f.strike} onChange={(v) => set("strike", v)} step="1" suffix="%" /></Field>
                <Field label="敲入障碍(下方)" hint="% of 初始"><NumInput value={f.barrier_lvl} onChange={(v) => set("barrier_lvl", v)} step="1" suffix="%" /></Field>
                <Field label="上行参与率" hint="1=100%"><NumInput value={f.call_parti} onChange={(v) => set("call_parti", v)} step="0.05" /></Field>
                <Field label="敲入后下行参与率"><NumInput value={f.knockin_parti} onChange={(v) => set("knockin_parti", v)} step="0.05" /></Field>
                <Field label="敲入后上行参与率"><NumInput value={f.reset_call_parti} onChange={(v) => set("reset_call_parti", v)} step="0.05" /></Field>
                <FieldSwitch label="每日离散观察" checked={f.discrete_obs as boolean} onChange={(v) => set("discrete_obs", v)} />
              </>
            )}
            {product === "barrier" && (
              <>
                <FieldSelect label="方向(上/下)" value={f.updown as string} onChange={(v) => set("updown", v)}
                  options={[{ value: "up", label: "向上 Up" }, { value: "down", label: "向下 Down" }]} />
                <FieldSelect label="敲入/敲出" value={f.inout as string} onChange={(v) => set("inout", v)}
                  options={[{ value: "out", label: "敲出 Out" }, { value: "in", label: "敲入 In" }]} />
                <FieldSelect label="看涨/看跌" value={f.callput as string} onChange={(v) => set("callput", v)}
                  options={[{ value: "call", label: "看涨 Call" }, { value: "put", label: "看跌 Put" }]} />
                <Field label="行权价" hint="% of 初始"><NumInput value={f.strike} onChange={(v) => set("strike", v)} step="1" suffix="%" /></Field>
                <Field label="障碍价" hint="% of 初始"><NumInput value={f.barrier_lvl} onChange={(v) => set("barrier_lvl", v)} step="1" suffix="%" /></Field>
                <Field label="rebate" hint="% of 初始, 触碰补偿"><NumInput value={f.rebate} onChange={(v) => set("rebate", v)} step="1" suffix="%" /></Field>
                <Field label="参与率"><NumInput value={f.parti} onChange={(v) => set("parti", v)} step="0.05" /></Field>
                <FieldSwitch label="每日离散观察" checked={f.discrete_obs as boolean} onChange={(v) => set("discrete_obs", v)} />
              </>
            )}
            {product !== "airbag" && product !== "barrier" && (
              <Field label="MC 路径数"><ThousandInput value={f.n_paths} onChange={(v) => set("n_paths", v)} /></Field>
            )}
          </div>

          {/* 敲出观察日预览 */}
          {showSnowballish && obsDates.length > 0 && (
            <div className="border-t border-border/50 pt-3">
              <div className="text-xs text-muted-foreground mb-1.5">
                敲出观察日 (共 {obsDates.length} 个, 非交易日已按下一交易日递延):
              </div>
              <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto">
                {obsDates.map((d) => (
                  <span key={d.effective ?? d.requested}
                    className={`text-[11px] font-mono px-1.5 py-0.5 rounded border ${
                      d.rolled ? "border-amber-500/40 text-amber-600 dark:text-amber-400" : "border-border text-muted-foreground"
                    }`}
                    title={d.rolled ? `原 ${d.requested} 递延` : undefined}>
                    {d.effective}{d.rolled ? " ↦" : ""}
                  </span>
                ))}
              </div>
            </div>
          )}

          {error && <div className="text-sm text-destructive">{error}</div>}
          {notice && <div className="text-sm text-primary">{notice}</div>}
          {pricing && progress && (
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>{progress.msg}</span>
                <span>{progress.cur}/{progress.total}</span>
              </div>
              <Progress value={(progress.cur / (progress.total || 7)) * 100} />
            </div>
          )}
        </CardContent>
      </Card>

      {/* 定价结果 */}
      {result && (
        <Card>
          <CardHeader className="border-b border-border/60 pb-4">
            <CardTitle className="text-base flex items-center gap-2">
              <LineChart className="w-4 h-4 text-primary" /> 定价结果
            </CardTitle>
          </CardHeader>
          <CardContent className="p-5">
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-5">
              <div className="space-y-1">
                <div className="text-xs text-muted-foreground">公允价值 (PV)</div>
                <div className={`text-2xl font-semibold font-mono tabular-nums ${result.price >= 0 ? "text-up" : "text-down"}`}>
                  ¥ {fmtMoney2(result.price)}
                </div>
                <div className="text-[11px] text-muted-foreground">
                  {result.status === "knocked_out" || result.meta?.terminated
                    ? "衍生品公允价值(不含本金)；已终止为0"
                    : `占名义 ${((result.price / parseThousand(f.notional)) * 100).toFixed(3)}%`}
                </div>
              </div>
              <div className="space-y-1">
                <div className="text-xs text-muted-foreground">盈亏</div>
                <div className={`text-2xl font-semibold font-mono tabular-nums ${(result.current_pnl ?? 0) >= 0 ? "text-up" : "text-down"}`}>
                  ¥ {fmtMoney2(result.current_pnl ?? null)}
                </div>
                <div className="text-[11px] text-muted-foreground">该期权累计总收益(相对期初)</div>
              </div>
              <div className="space-y-1">
                <div className="text-xs text-muted-foreground">存续名义本金</div>
                <div className="text-2xl font-semibold font-mono tabular-nums">¥ {fmtMoney(result.present_notional)}</div>
              </div>
              <div className="space-y-1">
                <div className="text-xs text-muted-foreground">当前状态</div>
                <Badge variant="outline" className={`text-sm ${statusBadgeClass(result.status)}`}>
                  {OTC_STATUS_LABELS[result.status] ?? result.status}
                </Badge>
              </div>
              <div className="space-y-1">
                <div className="text-xs text-muted-foreground">估值日 / 引擎</div>
                <div className="text-sm font-mono">{String(result.meta.valuation_date ?? "")} · {String(result.meta.engine ?? "").toUpperCase()}</div>
              </div>
            </div>
            {result.greeks && Object.keys(result.greeks).length > 0 && (
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                {([
                  ["Delta (Δ)", result.greeks.delta], ["Gamma (Γ)", result.greeks.gamma],
                  ["Vega (每1%vol)", result.greeks.vega], ["Theta (每日)", result.greeks.theta],
                  ["Rho (每1%r)", result.greeks.rho],
                ] as [string, number | undefined][]).map(([label, val]) => (
                  <div key={label} className="rounded-lg border border-border bg-muted/20 px-3 py-2">
                    <div className="text-[11px] text-muted-foreground">{label}</div>
                    <div className="text-sm font-mono tabular-nums">
                      {val == null ? "—" : val.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* 收益-波动示意图 */}
      {result && pathOption && (
        <Card>
          <CardHeader className="border-b border-border/60 pb-4">
            <CardTitle className="text-base flex items-center gap-2">
              <Activity className="w-4 h-4 text-primary" /> 收益-波动示意图
            </CardTitle>
            <p className="text-xs text-muted-foreground pt-1">
              横轴为初始观察日→估值日(敲出后截断至敲出日)。蓝线为挂钩指数; 红/绿虚线为敲入/敲出障碍
              (标签含百分比与点位, 纵轴始终同时可见两条线)。
              灰色点线为月度敲出观察日 — 仅观察日收盘≥敲出线才终止; 观察日之间上穿敲出线不算敲出。
              标记点仅表示已发生的敲入 / 敲出·终止; 橙线为累计盈亏。
            </p>
          </CardHeader>
          <CardContent className="p-3 sm:p-5">
            <EChart option={pathOption} style={{ height: 420, width: "100%" }} />
          </CardContent>
        </Card>
      )}

      {/* 簿记 */}
      <Card>
        <CardHeader className="border-b border-border/60 pb-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-base flex items-center gap-2">
              <Bookmark className="w-4 h-4 text-primary" /> 已簿记场外期权
              <Badge variant="secondary" className="font-normal">{filteredDeals.length}/{deals.length}</Badge>
            </CardTitle>
            {isWhitelisted && deals.length > 1 && (
              <DealReorderDialog deals={deals} onSaved={loadDeals} />
            )}
          </div>
          {deals.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <Select value={dealFilterProduct} onValueChange={setDealFilterProduct}>
                <SelectTrigger className={cn("h-8 w-32 text-xs", INPUT_BG)}><SelectValue placeholder="品种" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部品种</SelectItem>
                  {OTC_PRODUCTS.map((p) => (
                    <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Input
                placeholder="筛选标的/名称…"
                value={dealFilterSymbol}
                onChange={(e) => setDealFilterSymbol(e.target.value)}
                className={cn("h-8 w-40 text-xs", INPUT_BG)}
              />
            </div>
          )}
        </CardHeader>
        <CardContent className="p-0">
          {deals.length === 0 ? (
            <div className="p-8 text-center text-sm text-muted-foreground">
              {isWhitelisted ? "暂无簿记, 定价后点击「存为簿记」保存。" : "暂无示例簿记。登录后可簿记自己的场外期权。"}
            </div>
          ) : filteredDeals.length === 0 ? (
            <div className="p-8 text-center text-sm text-muted-foreground">无匹配簿记</div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>名称</TableHead>
                    <TableHead>
                      <button type="button" className="inline-flex items-center" onClick={() => toggleDealSort("product")}>
                        品种 <SortIcon k="product" />
                      </button>
                    </TableHead>
                    <TableHead>
                      <button type="button" className="inline-flex items-center" onClick={() => toggleDealSort("symbol")}>
                        标的 <SortIcon k="symbol" />
                      </button>
                    </TableHead>
                    <TableHead className="text-right">
                      <button type="button" className="inline-flex items-center ml-auto" onClick={() => toggleDealSort("notional")}>
                        名义本金 <SortIcon k="notional" />
                      </button>
                    </TableHead>
                    <TableHead className="text-right">最新估值</TableHead>
                    <TableHead className="text-right">
                      <button type="button" className="inline-flex items-center ml-auto" onClick={() => toggleDealSort("pnl")}>
                        盈亏(PnL) <SortIcon k="pnl" />
                      </button>
                    </TableHead>
                    <TableHead>起始日</TableHead>
                    <TableHead>到期日</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredDeals.map((d) => {
                    const canEdit = isSuperAdmin || (userId != null && d.owner_user_id === userId);
                    const pnl = d.last_result?.current_pnl;
                    return (
                      <TableRow key={d.deal_id}>
                        <TableCell className="font-medium">
                          <div className="flex items-center gap-1.5">
                            {d.is_example && <Star className="w-3.5 h-3.5 text-amber-500 fill-amber-500" />}
                            {d.name}
                          </div>
                        </TableCell>
                        <TableCell>{OTC_PRODUCTS.find((p) => p.value === d.product_type)?.label ?? d.product_type}</TableCell>
                        <TableCell className="font-mono text-xs">{d.underlying_symbol}</TableCell>
                        <TableCell className="text-right font-mono tabular-nums">{fmtMoney(d.terms?.notional)}</TableCell>
                        <TableCell className="text-right font-mono tabular-nums">
                          {d.last_price != null ? `¥ ${fmtMoney(d.last_price)}` : "—"}
                        </TableCell>
                        <TableCell className={`text-right font-mono tabular-nums ${
                          pnl == null ? "" : pnl >= 0 ? "text-up" : "text-down"
                        }`}>
                          {pnl != null ? `¥ ${fmtMoney2(pnl)}` : "—"}
                        </TableCell>
                        <TableCell className="font-mono text-xs tabular-nums">
                          {d.terms?.start_date ? isoToSlash(String(d.terms.start_date).slice(0, 10)) : "—"}
                        </TableCell>
                        <TableCell className="font-mono text-xs tabular-nums">
                          {d.terms?.maturity_date ? isoToSlash(String(d.terms.maturity_date).slice(0, 10)) : "—"}
                        </TableCell>
                        <TableCell>
                          {d.last_status ? (
                            <Badge variant="outline" className={`text-xs ${statusBadgeClass(d.last_status)}`}>
                              {OTC_STATUS_LABELS[d.last_status] ?? d.last_status}
                            </Badge>
                          ) : <span className="text-xs text-muted-foreground">未估值</span>}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1">
                            <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => canPrice ? loadDealIntoForm(d) : viewExampleResult(d)}>
                              {canPrice ? "载入" : "查看"}
                            </Button>
                            <Button variant="ghost" size="icon" className="h-7 w-7" title="重估"
                              onClick={() => repriceDeal(d)} disabled={repricingId === d.deal_id}>
                              {repricingId === d.deal_id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                            </Button>
                            {isSuperAdmin && (
                              <Button variant="ghost" size="icon" className="h-7 w-7" title={d.is_example ? "取消示例" : "设为示例"}
                                onClick={() => toggleExample(d)}>
                                <Star className={`w-3.5 h-3.5 ${d.is_example ? "text-amber-500 fill-amber-500" : ""}`} />
                              </Button>
                            )}
                            {canEdit && (
                              <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" title="删除"
                                onClick={() => deleteDeal(d)}>
                                <Trash2 className="w-3.5 h-3.5" />
                              </Button>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* 挂钩指数历史波动率 */}
      <Card>
        <CardHeader className="border-b border-border/60 pb-4">
          <CardTitle className="text-base flex items-center gap-2">
            <LineChart className="w-4 h-4 text-primary" /> 挂钩指数历史波动率
          </CardTitle>
          <div className="flex flex-col sm:flex-row sm:flex-wrap items-start sm:items-center gap-2 pt-2">
            <div className="flex flex-wrap items-center gap-1">
              {OTC_VOL_WINDOWS.map((w) => (
                <button key={w} onClick={() => setVolWindow(w)}
                  className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${
                    volWindow === w ? "bg-primary text-primary-foreground border-primary"
                      : "border-border text-muted-foreground hover:text-foreground"
                  }`}>
                  {w}日
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-1">
              {([3, 5] as const).map((y) => (
                <button key={y} type="button" onClick={() => setVolRangeYears(y)}
                  className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${
                    volRangeYears === y ? "bg-primary text-primary-foreground border-primary"
                      : "border-border text-muted-foreground hover:text-foreground"
                  }`}>
                  近{y}年
                </button>
              ))}
            </div>
            <span className="text-xs text-muted-foreground">常用指数:</span>
            <div className="flex flex-wrap gap-1.5">
              {OTC_VOL_QUICK.map((q) => {
                const on = volSymbols.includes(q.symbol);
                return (
                  <button key={q.symbol} type="button"
                    onClick={() => setVolSymbols((prev) => on ? prev.filter((s) => s !== q.symbol) : [...prev, q.symbol])}
                    className={`px-2 py-1 rounded text-xs border transition-colors ${
                      on ? "bg-primary/10 border-primary/40 text-primary" : "border-border text-muted-foreground hover:text-foreground"
                    }`}>
                    {q.label}
                  </button>
                );
              })}
            </div>
            <Popover open={volPickerOpen} onOpenChange={setVolPickerOpen}>
              <PopoverTrigger asChild>
                <Button variant="outline" size="sm" className="h-8"><Search className="w-3.5 h-3.5 mr-1" />搜索指数</Button>
              </PopoverTrigger>
              <PopoverContent className="w-72 p-0" align="start">
                <Command>
                  <CommandInput placeholder="搜索指数代码或名称…" />
                  <CommandList>
                    <CommandEmpty>无匹配</CommandEmpty>
                    <CommandGroup>
                      {indexUnderlyings.map((u) => (
                        <CommandItem key={u.symbol} value={`${u.symbol} ${u.name ?? ""}`}
                          onSelect={() => {
                            setVolSymbols((prev) => prev.includes(u.symbol) ? prev : [...prev, u.symbol]);
                            setVolPickerOpen(false);
                          }}>
                          {u.name ?? u.symbol} ({u.symbol})
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  </CommandList>
                </Command>
              </PopoverContent>
            </Popover>
            {/* {volSymbols.length > 0 && (
              <div className="flex flex-wrap gap-1.5 w-full">
                {volSymbols.map((sym) => {
                  const u = indexUnderlyings.find((x) => x.symbol === sym);
                  return (
                    <button key={sym} type="button" onClick={() => setVolSymbols((p) => p.filter((s) => s !== sym))}
                      className="px-2 py-1 rounded-full text-xs bg-primary/10 border border-primary/30 text-primary">
                      {u?.name ?? sym} ×
                    </button>
                  );
                })}
              </div>
            )} */}
          </div>
        </CardHeader>
        <CardContent className="p-3 sm:p-5">
          {volLoading ? (
            <div className="h-[320px] flex items-center justify-center text-sm text-muted-foreground">
              <Loader2 className="w-4 h-4 mr-2 animate-spin" /> 计算中…
            </div>
          ) : volOption ? (
            <EChart option={volOption} style={{ height: 360, width: "100%" }} />
          ) : (
            <div className="h-[320px] flex items-center justify-center text-sm text-muted-foreground">
              选择一个或多个指数以查看 {volWindow} 日滚动年化波动率
            </div>
          )}
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground/70 text-center pb-4">
        定价结果仅供研究参考，不构成投资建议。蒙特卡洛与真实交易系统存在模型/约定差异。
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 小组件
// ---------------------------------------------------------------------------
function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-muted-foreground">{label}</label>
      {children}
      {hint && <p className="text-[10px] text-muted-foreground/60">{hint}</p>}
    </div>
  );
}

function ThousandInput({ value, onChange }: { value: string | boolean; onChange: (v: string) => void }) {
  const [local, setLocal] = useState(String(value));
  useEffect(() => { setLocal(formatThousand(value)); }, [value]);
  return (
    <Input
      inputMode="numeric"
      value={local}
      onChange={(e) => setLocal(e.target.value.replace(/[^\d,]/g, ""))}
      onBlur={() => onChange(formatThousand(local))}
      className={cn("h-9 font-mono tabular-nums", INPUT_BG)}
    />
  );
}

function NumInput({
  value, onChange, step, suffix,
}: { value: string | boolean; onChange: (v: string) => void; step?: string; suffix?: string }) {
  return (
    <div className="relative">
      <Input
        type="number" step={step} value={String(value)}
        onChange={(e) => onChange(e.target.value)}
        className={cn("h-9 font-mono tabular-nums", INPUT_BG, suffix ? "pr-7" : "")}
      />
      {suffix && <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-muted-foreground pointer-events-none">{suffix}</span>}
    </div>
  );
}

function FieldSelect({
  label, value, onChange, options, placeholder,
}: {
  label: string; value: string; onChange: (v: string) => void;
  options: { value: string; label: string }[]; placeholder?: string;
}) {
  return (
    <Field label={label}>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger className={cn("h-9", INPUT_BG)}><SelectValue placeholder={placeholder} /></SelectTrigger>
        <SelectContent>
          {options.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
        </SelectContent>
      </Select>
    </Field>
  );
}

function FieldSwitch({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-lg border border-border px-3 h-9 mt-5 bg-background">
      <span className="text-xs font-medium text-muted-foreground flex items-center gap-1">
        <Lock className="w-3 h-3" /> {label}
      </span>
      <Switch checked={checked} onCheckedChange={onChange} />
    </div>
  );
}

/** YYYY/MM/DD 可键盘输入 + 日历选择, 内部存 ISO YYYY-MM-DD */
function DateField({
  label, value, onChange,
}: { label: string; value: string; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(isoToSlash(value));
  useEffect(() => { setText(isoToSlash(value)); }, [value]);

  const commit = () => {
    const iso = parseSlashOrIsoDate(text);
    if (iso) onChange(iso);
    else setText(isoToSlash(value));
  };

  const selected = value ? new Date(value + "T00:00:00") : undefined;
  return (
    <Field label={label}>
      <div className="flex gap-1">
        <Input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }}
          placeholder="YYYY/MM/DD"
          className={cn("h-9 font-mono tabular-nums", INPUT_BG)}
        />
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <Button
              type="button"
              variant="outline"
              className={cn("h-9 w-9 shrink-0 px-0", INPUT_BG)}
              title="选择日期"
            >
              <CalendarIcon className="h-3.5 w-3.5 opacity-60" />
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="end">
            <Calendar
              mode="single"
              selected={selected}
              defaultMonth={selected}
              onSelect={(d) => {
                if (!d) return;
                onChange(toIsoDate(d));
                setOpen(false);
              }}
            />
          </PopoverContent>
        </Popover>
      </div>
    </Field>
  );
}

function DealReorderDialog({ deals, onSaved }: { deals: OtcDeal[]; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<OtcDeal[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) setItems(deals);
  }, [open, deals]);

  const move = (i: number, dir: -1 | 1) => {
    setItems((arr) => {
      const j = i + dir;
      if (j < 0 || j >= arr.length) return arr;
      const next = arr.slice();
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  };

  const save = async () => {
    setBusy(true);
    try {
      await api.otcReorderDeals(items.map((d) => d.deal_id));
      onSaved();
      setOpen(false);
    } catch (e) {
      window.alert(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className={cn("shrink-0", INPUT_BG)} title="调整簿记顺序">
          <ArrowUpDown className="w-3.5 h-3.5" /> 排序
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader><DialogTitle>调整簿记顺序</DialogTitle></DialogHeader>
        <p className="text-xs text-muted-foreground">仅影响你自己看到的列表顺序；示例簿记固定排在前。</p>
        <div className="max-h-[50vh] overflow-auto space-y-1.5 pr-1">
          {items.map((d, i) => (
            <div key={d.deal_id} className="flex items-center gap-2 rounded-md border border-border px-3 py-2">
              <span className="flex-1 truncate text-sm">
                {d.is_example && <Badge variant="secondary" className="mr-1.5 font-normal">示例</Badge>}
                {d.name}
                {!d.is_example && <span className="text-muted-foreground"> #{d.deal_id}</span>}
              </span>
              <Button variant="ghost" size="icon" className="h-7 w-7" disabled={i === 0} onClick={() => move(i, -1)}>
                <ArrowUp className="w-4 h-4" />
              </Button>
              <Button variant="ghost" size="icon" className="h-7 w-7" disabled={i === items.length - 1} onClick={() => move(i, 1)}>
                <ArrowDown className="w-4 h-4" />
              </Button>
            </div>
          ))}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>取消</Button>
          <Button onClick={save} disabled={busy}>{busy ? "保存中..." : "保存顺序"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** 可搜索的挂钩标的单选 */
function UnderlyingCombobox({
  underlyings, value, open, onOpenChange, onChange,
}: {
  underlyings: OtcUnderlying[];
  value: string;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onChange: (symbol: string, source: string) => void;
}) {
  const selected = underlyings.find((u) => u.symbol === value);
  return (
    <Field label="挂钩标的(指数)">
      <Popover open={open} onOpenChange={onOpenChange}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={open}
            className={cn("h-9 w-full justify-between font-normal", INPUT_BG)}
          >
            <span className="truncate">
              {selected
                ? `${selected.name ?? selected.symbol} (${selected.symbol})`
                : value || "搜索选择指数…"}
            </span>
            <ChevronsUpDown className="ml-2 h-3.5 w-3.5 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0" align="start">
          <Command>
            <CommandInput placeholder="搜索指数代码或名称…" />
            <CommandList>
              <CommandEmpty>无匹配</CommandEmpty>
              <CommandGroup>
                {underlyings.map((u) => (
                  <CommandItem
                    key={u.symbol}
                    value={`${u.symbol} ${u.name ?? ""}`}
                    onSelect={() => {
                      onChange(u.symbol, u.source);
                      onOpenChange(false);
                    }}
                  >
                    <Check className={cn("mr-2 h-3.5 w-3.5", value === u.symbol ? "opacity-100" : "opacity-0")} />
                    {u.name ?? u.symbol} ({u.symbol})
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </Field>
  );
}
