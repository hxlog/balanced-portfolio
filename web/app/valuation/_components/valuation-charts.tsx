"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
} from "react";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { EChart } from "@/components/EChart";
import { getChartTheme, type ChartTheme } from "@/lib/chart-theme";
import { cn } from "@/lib/utils";
import {
  formatNumber,
  formatPercentile,
  formatPlainPct,
} from "@/lib/valuation-mock";
import type { IndexQuoteRow } from "@/lib/valuation-types";
import { ChartCard } from "./valuation-ui";

const BIN_LABELS = Array.from({ length: 10 }, (_, index) => {
  const start = index * 10;
  return `${start}–${start + 10}`;
});

interface HistogramBin {
  label: string;
  start: number;
  end: number;
  count: number;
}

function buildHistogram(rows: readonly IndexQuoteRow[]): HistogramBin[] {
  const bins: HistogramBin[] = BIN_LABELS.map((label, index) => ({
    label,
    start: index * 10,
    end: index * 10 + 10,
    count: 0,
  }));
  for (const row of rows) {
    const pct = row.pe_percentile;
    if (pct == null || !Number.isFinite(pct)) continue;
    const index = pct >= 100 ? 9 : Math.min(9, Math.max(0, Math.floor(pct / 10)));
    bins[index].count += 1;
  }
  return bins;
}

interface SemanticChartColors {
  success: string;
  danger: string;
  neutral: string;
}

/** 语义色从 CSS token 读取；服务端渲染时回退到 chart-theme，避免任何硬编码 hex。 */
function readSemanticColors(theme: ChartTheme): SemanticChartColors {
  const fallback: SemanticChartColors = {
    success: theme.up,
    danger: theme.down,
    neutral: theme.palette[0],
  };
  if (typeof window === "undefined") return fallback;
  const styles = getComputedStyle(document.documentElement);
  const read = (name: string, value: string) =>
    styles.getPropertyValue(name).trim() || value;
  return {
    success: read("--success", fallback.success),
    danger: read("--destructive", fallback.danger),
    neutral: read("--primary", fallback.neutral),
  };
}

function binColor(bin: HistogramBin, colors: SemanticChartColors): string {
  if (bin.end <= 30) return colors.success;
  if (bin.start >= 70) return colors.danger;
  return colors.neutral;
}

export function PercentileHistogramCard({
  rows,
}: {
  rows: readonly IndexQuoteRow[];
}) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const theme = getChartTheme(isDark);
  const bins = useMemo(() => buildHistogram(rows), [rows]);
  const validCount = bins.reduce((sum, bin) => sum + bin.count, 0);
  const colors = useMemo(() => readSemanticColors(theme), [theme]);

  const option = useMemo<Record<string, unknown>>(() => {
    return {
      animation: false,
      grid: { left: 4, right: 8, top: 22, bottom: 2, containLabel: true },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        backgroundColor: theme.tooltipBg,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.text, fontSize: 12 },
        formatter: (params: unknown) => {
          const first = Array.isArray(params)
            ? (params[0] as { dataIndex?: number } | undefined)
            : undefined;
          const index = first?.dataIndex;
          const bin = index == null ? undefined : bins[index];
          if (!bin) return "";
          return `${bin.label}%　${formatNumber(bin.count, 0)} 只`;
        },
      },
      xAxis: {
        type: "category",
        data: bins.map((bin) => bin.label),
        axisLine: { lineStyle: { color: theme.axisLine } },
        axisTick: { show: false },
        axisLabel: {
          color: theme.subtext,
          fontSize: 9,
          interval: 0,
          margin: 8,
        },
      },
      yAxis: {
        type: "value",
        minInterval: 1,
        splitNumber: 3,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: theme.subtext, fontSize: 10 },
        splitLine: { lineStyle: { color: theme.splitLine } },
      },
      series: [
        {
          name: "指数数量",
          type: "bar",
          barWidth: "62%",
          data: bins.map((bin) => ({
            value: bin.count,
            itemStyle: {
              color: binColor(bin, colors),
              borderRadius: [4, 4, 0, 0],
            },
          })),
          label: {
            show: true,
            position: "top",
            color: theme.subtext,
            fontSize: 9,
            formatter: (params: { value?: unknown }) =>
              typeof params.value === "number" && params.value > 0
                ? String(params.value)
                : "",
          },
        },
      ],
    };
  }, [bins, colors, theme]);

  return (
    <ChartCard
      title="估值分位分布"
      hint="PE 5 年分位 · 每 10% 一档"
      aside={
        <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
          {formatNumber(validCount, 0)} 只
        </span>
      }
    >
      <div
        role="img"
        aria-label={`PE 分位直方图，共 ${validCount} 只指数`}
      >
        <EChart option={option} style={{ height: 240, width: "100%" }} />
      </div>
      <ul className="sr-only">
        {bins.map((bin) => (
          <li key={bin.label}>
            PE 分位 {bin.label}%：{bin.count} 只
          </li>
        ))}
      </ul>
    </ChartCard>
  );
}

const MARKET_ORDER = [
  "CSI",
  "SH",
  "SZ",
  "CNI",
  "HK",
  "US",
  "BJ",
  "GLOBAL",
] as const;

const MARKET_LABEL: Record<string, string> = {
  CSI: "中证",
  SH: "上证",
  SZ: "深证",
  CNI: "国证",
  HK: "港股",
  US: "美股",
  BJ: "北交所",
  GLOBAL: "全球",
};

function marketLabel(market: string): string {
  return MARKET_LABEL[market] ?? market;
}

function marketColor(market: string, theme: ChartTheme): string {
  const index = MARKET_ORDER.indexOf(market as (typeof MARKET_ORDER)[number]);
  if (index < 0) return theme.subtext;
  return theme.palette[index % theme.palette.length];
}

interface ScatterPoint {
  row: IndexQuoteRow;
  market: string;
  pe: number;
  dividend: number;
  pct: number | null;
  radius: number;
  color: string;
}

function useElementWidth() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(640);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const update = () => {
      const next = element.getBoundingClientRect().width;
      if (next > 0) setWidth(Math.max(240, next));
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return { ref, width };
}

const SCATTER_HEIGHT = 240;

function niceYieldMax(value: number): number {
  if (value <= 2) return 2;
  if (value <= 4) return 4;
  if (value <= 6) return 6;
  if (value <= 8) return 8;
  if (value <= 10) return 10;
  return Math.ceil(value / 5) * 5;
}

const PE_TICKS = [1, 2, 3, 5, 10, 20, 30, 50, 100, 200, 300, 500, 1000];

export function PeDividendScatterCard({
  rows,
}: {
  rows: readonly IndexQuoteRow[];
}) {
  const router = useRouter();
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const theme = getChartTheme(isDark);
  const { ref, width } = useElementWidth();
  const [hiddenMarkets, setHiddenMarkets] = useState<ReadonlySet<string>>(
    new Set(),
  );
  const [hover, setHover] = useState<{
    x: number;
    y: number;
    point: ScatterPoint;
  } | null>(null);

  const points = useMemo<ScatterPoint[]>(() => {
    return rows.flatMap((row) => {
      const pe = row.pe_ttm;
      const dividend = row.dividend_yield_pct;
      if (pe == null || pe <= 0 || dividend == null || !Number.isFinite(dividend)) {
        return [];
      }
      const pct =
        row.pe_percentile != null && Number.isFinite(row.pe_percentile)
          ? row.pe_percentile
          : null;
      const market = row.market ?? "OTHER";
      return [
        {
          row,
          market,
          pe,
          dividend,
          pct,
          radius: pct == null ? 3.5 : 3.5 + (pct / 100) * 9,
          color: marketColor(market, theme),
        },
      ];
    });
  }, [rows, theme]);

  const markets = useMemo(() => {
    const counts = new Map<string, number>();
    for (const point of points) {
      counts.set(point.market, (counts.get(point.market) ?? 0) + 1);
    }
    const order = [...MARKET_ORDER, "OTHER"];
    return order
      .filter((market) => counts.has(market))
      .map((market) => ({
        market,
        label: market === "OTHER" ? "其他" : marketLabel(market),
        color: marketColor(market, theme),
        count: counts.get(market) ?? 0,
      }));
  }, [points, theme]);

  const visiblePoints = useMemo(
    () => points.filter((point) => !hiddenMarkets.has(point.market)),
    [points, hiddenMarkets],
  );
  const sortedPoints = useMemo(
    () => [...visiblePoints].sort((a, b) => b.radius - a.radius),
    [visiblePoints],
  );

  const geometry = useMemo(() => {
    const left = 40;
    const right = 12;
    const top = 14;
    const bottom = 28;
    const plotWidth = Math.max(1, width - left - right);
    const plotHeight = SCATTER_HEIGHT - top - bottom;
    const peValues = points.map((point) => point.pe);
    const dividends = points.map((point) => point.dividend);
    const xMin = Math.max(0.1, Math.min(...peValues) * 0.85);
    const xMax = Math.max(xMin * 2, Math.max(...peValues) * 1.08);
    const yMax = niceYieldMax(Math.max(0.5, ...dividends));
    const logMin = Math.log10(xMin);
    const logMax = Math.log10(xMax);
    const xScale = (value: number) =>
      left + ((Math.log10(value) - logMin) / (logMax - logMin)) * plotWidth;
    const yScale = (value: number) =>
      top + (1 - Math.min(1, Math.max(0, value / yMax))) * plotHeight;
    const xTicks = PE_TICKS.filter((tick) => tick >= xMin && tick <= xMax);
    return {
      left,
      right,
      top,
      bottom,
      plotWidth,
      plotHeight,
      xMin,
      xMax,
      yMax,
      xScale,
      yScale,
      xTicks: xTicks.length > 0 ? xTicks : [xMin, xMax],
    };
  }, [points, width]);

  const navigate = (event: MouseEvent<HTMLAnchorElement>, code: string) => {
    if (
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey ||
      event.button !== 0
    ) {
      return;
    }
    event.preventDefault();
    router.push(`/valuation/${encodeURIComponent(code)}`);
  };

  const toggleMarket = (market: string) => {
    setHiddenMarkets((previous) => {
      const next = new Set(previous);
      if (next.has(market)) next.delete(market);
      else next.add(market);
      return next;
    });
  };

  return (
    <ChartCard
      title="PE × 股息率"
      hint="点大小 = PE 分位 · 颜色 = 市场"
      aside={
        <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
          {formatNumber(visiblePoints.length, 0)} 只
        </span>
      }
      bodyClassName="px-3 pb-3"
    >
      {points.length === 0 ? (
        <div
          className="flex items-center justify-center text-xs text-muted-foreground"
          style={{ height: SCATTER_HEIGHT }}
        >
          暂无可绘制的 PE / 股息率数据
        </div>
      ) : (
        <div
          ref={ref}
          className="relative w-full"
          style={{ height: SCATTER_HEIGHT }}
        >
          <svg
            width={width}
            height={SCATTER_HEIGHT}
            viewBox={`0 0 ${width} ${SCATTER_HEIGHT}`}
            style={{ width: "100%", height: SCATTER_HEIGHT }}
            role="group"
            aria-label={`PE 与股息率散点图，共 ${visiblePoints.length} 只指数；圆点越大 PE 分位越高，点击圆点查看详情`}
          >
            {[0, 0.5, 1].map((fraction) => {
              const value = geometry.yMax * fraction;
              const y = geometry.yScale(value);
              return (
                <g key={`y-${fraction}`}>
                  <line
                    x1={geometry.left}
                    x2={width - geometry.right}
                    y1={y}
                    y2={y}
                    stroke={theme.splitLine}
                  />
                  <text
                    x={geometry.left - 6}
                    y={y + 3}
                    textAnchor="end"
                    fill={theme.subtext}
                    fontSize={9}
                  >
                    {value.toFixed(1)}
                  </text>
                </g>
              );
            })}

            {geometry.xTicks.map((tick) => {
              const x = geometry.xScale(tick);
              return (
                <g key={`x-${tick}`}>
                  <line
                    x1={x}
                    x2={x}
                    y1={geometry.top}
                    y2={SCATTER_HEIGHT - geometry.bottom}
                    stroke={theme.splitLine}
                    opacity={0.55}
                  />
                  <text
                    x={x}
                    y={SCATTER_HEIGHT - geometry.bottom + 14}
                    textAnchor="middle"
                    fill={theme.subtext}
                    fontSize={9}
                  >
                    {tick}
                  </text>
                </g>
              );
            })}

            <line
              x1={geometry.left}
              x2={width - geometry.right}
              y1={SCATTER_HEIGHT - geometry.bottom}
              y2={SCATTER_HEIGHT - geometry.bottom}
              stroke={theme.axisLine}
            />
            <text
              x={width - geometry.right}
              y={SCATTER_HEIGHT - 2}
              textAnchor="end"
              fill={theme.subtext}
              fontSize={9}
            >
              PE (TTM, 对数)
            </text>
            <text
              x={geometry.left}
              y={11}
              fill={theme.subtext}
              fontSize={9}
            >
              股息率 %
            </text>

            {sortedPoints.map((point) => {
                const x = geometry.xScale(point.pe);
                const y = geometry.yScale(point.dividend);
                return (
                  <g
                    key={`${point.row.index_code}-${point.row.trade_date}`}
                    onMouseEnter={() => setHover({ x, y, point })}
                    onMouseLeave={() => setHover(null)}
                    onFocus={() => setHover({ x, y, point })}
                    onBlur={() => setHover(null)}
                  >
                    <a
                      href={`/valuation/${encodeURIComponent(point.row.index_code)}`}
                      onClick={(event) => navigate(event, point.row.index_code)}
                      tabIndex={-1}
                      aria-label={`${point.row.name}，PE ${formatNumber(point.pe)}，股息率 ${formatPlainPct(point.dividend)}，PE 分位 ${formatPercentile(point.pct)}`}
                      className="cursor-pointer outline-none"
                    >
                      <circle
                        cx={x}
                        cy={y}
                        r={Math.max(9, point.radius + 5)}
                        fill="transparent"
                      />
                      <circle
                        cx={x}
                        cy={y}
                        r={point.radius}
                        fill={point.color}
                        fillOpacity={0.78}
                        stroke={theme.tooltipBg}
                        strokeWidth={1.5}
                      />
                    </a>
                  </g>
                );
              })}
          </svg>

          {hover && (
            <div
              className="pointer-events-none absolute z-20 w-[190px] rounded-lg border border-border bg-popover px-3 py-2 text-popover-foreground shadow-md"
              style={{
                left: Math.max(
                  4,
                  Math.min(width - 194, hover.x + 10),
                ),
                top: Math.max(
                  4,
                  Math.min(SCATTER_HEIGHT - 86, hover.y - 8),
                ),
              }}
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="truncate text-xs font-medium">
                  {hover.point.row.name}
                </span>
                <span className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">
                  {hover.point.row.index_code}
                </span>
              </div>
              <div className="mt-1.5 grid grid-cols-3 gap-1 text-[10px] tabular-nums text-muted-foreground">
                <span>PE {formatNumber(hover.point.pe)}</span>
                <span>息 {formatPlainPct(hover.point.dividend)}</span>
                <span>分位 {formatPercentile(hover.point.pct)}</span>
              </div>
            </div>
          )}
        </div>
      )}

      {markets.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1.5 px-1">
          {markets.map((market) => {
            const hidden = hiddenMarkets.has(market.market);
            return (
              <button
                key={market.market}
                type="button"
                onClick={() => toggleMarket(market.market)}
                aria-pressed={!hidden}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-[10px] text-muted-foreground transition-opacity hover:border-primary/30 hover:text-foreground",
                  hidden && "opacity-35",
                )}
              >
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{ backgroundColor: market.color }}
                  aria-hidden="true"
                />
                {market.label}
                <span className="tabular-nums">{market.count}</span>
              </button>
            );
          })}
        </div>
      )}

      <p className="sr-only">
        横轴为 PE (TTM)，纵轴为股息率，圆点越大表示 PE 历史分位越高；点击圆点进入指数详情。
        完整数值见下方指数列表。
      </p>
    </ChartCard>
  );
}
