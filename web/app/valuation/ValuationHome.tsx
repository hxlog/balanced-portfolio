"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ArrowUpRight,
  Search,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import type {
  IndexQuoteRow,
  MarketValuationCard,
} from "@/lib/valuation-types";
import {
  changeClass,
  filterIndexRows,
  formatNumber,
  formatPercentile,
  formatPlainPct,
  formatSignedPct,
  type IndexCategoryFilter,
} from "@/lib/valuation-mock";
import {
  PeDividendScatterCard,
  PercentileHistogramCard,
} from "./_components/valuation-charts";
import {
  boardRank,
  PercentileBar,
  percentileLabel,
  percentileTone,
  SectionHeading,
  Surface,
} from "./_components/valuation-ui";

const CATEGORY_OPTIONS: ReadonlyArray<{
  value: IndexCategoryFilter;
  label: string;
}> = [
  { value: "all", label: "全部" },
  { value: "宽基", label: "宽基" },
  { value: "行业", label: "行业" },
  { value: "主题", label: "主题" },
  { value: "策略", label: "策略" },
];

type OptionalColumnKey =
  | "close"
  | "changePct"
  | "pbPercentile"
  | "riskPremium";

const OPTIONAL_COLUMNS: ReadonlyArray<{
  key: OptionalColumnKey;
  label: string;
}> = [
  { key: "close", label: "收盘" },
  { key: "changePct", label: "当日涨跌" },
  { key: "pbPercentile", label: "PB 分位" },
  { key: "riskPremium", label: "风险溢价" },
];

const DEFAULT_OPTIONAL_COLUMNS: Record<OptionalColumnKey, boolean> = {
  close: false,
  changePct: false,
  pbPercentile: false,
  riskPremium: false,
};

type SortKey = "name" | "pe" | "pb" | "dividend" | "percentile" | "change" | OptionalColumnKey;
type SortState = { key: SortKey; direction: "asc" | "desc" } | null;

function sortValue(row: IndexQuoteRow, key: SortKey): string | number | null {
  switch (key) {
    case "name":
      return row.name;
    case "pe":
      return row.pe_ttm;
    case "pb":
      return row.pb;
    case "dividend":
      return row.dividend_yield_pct;
    case "percentile":
      return row.pe_percentile;
    case "change":
      return row.change_7d_pct ?? row.change_pct;
    case "close":
      return row.close;
    case "changePct":
      return row.change_pct;
    case "pbPercentile":
      return row.pb_percentile;
    case "riskPremium":
      return row.risk_premium_pct;
    default:
      return null;
  }
}

function compareRows(
  a: IndexQuoteRow,
  b: IndexQuoteRow,
  key: SortKey,
  direction: "asc" | "desc",
): number {
  const left = sortValue(a, key);
  const right = sortValue(b, key);
  if (left == null && right == null) {
    return a.index_code.localeCompare(b.index_code);
  }
  if (left == null) return 1;
  if (right == null) return -1;
  const result =
    typeof left === "string" && typeof right === "string"
      ? left.localeCompare(right, "zh-CN")
      : Number(left) - Number(right);
  return direction === "asc" ? result : -result;
}

function SortHeader({
  label,
  column,
  sort,
  onSort,
  align = "right",
  title,
  sticky = false,
}: {
  label: string;
  column: SortKey;
  sort: SortState;
  onSort: (key: SortKey) => void;
  align?: "left" | "right";
  title?: string;
  sticky?: boolean;
}) {
  const active = sort != null && sort.key === column;
  const Icon =
    sort != null && sort.key === column
      ? sort.direction === "asc"
        ? ArrowUp
        : ArrowDown
      : ArrowUpDown;
  return (
    <th
      scope="col"
      aria-sort={
        sort != null && sort.key === column
          ? sort.direction === "asc"
            ? "ascending"
            : "descending"
          : "none"
      }
      className={cn(
        "px-3 py-2 text-[11px] font-medium text-muted-foreground",
        align === "right" ? "text-right" : "text-left",
        sticky && "sticky left-0 z-20 bg-muted",
      )}
    >
      <button
        type="button"
        onClick={() => onSort(column)}
        title={title}
        className={cn(
          "inline-flex items-center gap-1 rounded-sm px-0.5 py-0.5 transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          active && "text-foreground",
        )}
      >
        {label}
        <Icon
          className={cn("h-3 w-3 shrink-0", !active && "opacity-35")}
          aria-hidden="true"
        />
      </button>
    </th>
  );
}

function MarketCard({ card }: { card: MarketValuationCard }) {
  const pct = card.pe_percentile;
  const label = percentileLabel(pct);

  return (
    <Surface className="flex min-h-[156px] flex-col p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium">{card.label}</span>
        <span
          className={cn(
            "text-[11px] tabular-nums",
            percentileTone(pct),
          )}
          title={label ? `PE ${label}` : "PE 分位样本不足"}
        >
          {pct == null ? "样本不足" : `${pct.toFixed(1)}%`}
        </span>
      </div>

      <div className="mt-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] text-muted-foreground">PE 中位数</div>
          <div className="mt-0.5 text-3xl font-semibold leading-none tracking-tight tabular-nums">
            {formatNumber(card.pe)}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-[10px] text-muted-foreground">PB</div>
          <div className="mt-0.5 text-base font-medium leading-none tabular-nums">
            {formatNumber(card.pb)}
          </div>
          <div
            className={cn(
              "mt-1 text-[10px] tabular-nums",
              percentileTone(card.pb_percentile),
            )}
          >
            {formatPercentile(card.pb_percentile, 1)}
          </div>
        </div>
      </div>

      <PercentileBar
        value={pct}
        label="PE 分位"
        className="mt-auto min-h-10 pt-3"
      />

      {card.history_days < 120 && (
        <div className="mt-1 text-[10px] text-warning">样本积累中</div>
      )}
    </Surface>
  );
}

function IndexTable({
  rows,
  sort,
  onSort,
  optionalColumns,
}: {
  rows: readonly IndexQuoteRow[];
  sort: SortState;
  onSort: (key: SortKey) => void;
  optionalColumns: Record<OptionalColumnKey, boolean>;
}) {
  const optionalCount = OPTIONAL_COLUMNS.filter(
    (column) => optionalColumns[column.key],
  ).length;

  return (
    <Surface className="overflow-hidden">
      <div className="overflow-x-auto overscroll-x-contain">
        <table
          className={cn(
            "w-full border-collapse text-sm",
            optionalCount > 0 ? "min-w-[1000px]" : "min-w-[780px]",
          )}
        >
          <caption className="sr-only">
            指数估值表，可按名称、PE、PB、股息率、分位与涨跌排序
          </caption>
          <thead>
            <tr className="whitespace-nowrap border-b border-border bg-muted">
              <SortHeader
                label="名称"
                column="name"
                sort={sort}
                onSort={onSort}
                align="left"
                sticky
              />
              <SortHeader label="PE" column="pe" sort={sort} onSort={onSort} />
              <SortHeader label="PB" column="pb" sort={sort} onSort={onSort} />
              <SortHeader
                label="股息率"
                column="dividend"
                sort={sort}
                onSort={onSort}
              />
              <SortHeader
                label="PE 分位"
                column="percentile"
                sort={sort}
                onSort={onSort}
                title="近 5 年历史分位；样本不足显示「—」"
              />
              <SortHeader
                label="7 日"
                column="change"
                sort={sort}
                onSort={onSort}
                title="接口提供 7 日涨跌时展示 7 日，否则展示最近交易日涨跌"
              />
              <th
                scope="col"
                className="px-3 py-2 text-right text-[11px] font-medium text-muted-foreground"
                title="当前收盘在近 52 周高低区间中的位置（0=最低，100=最高）"
              >
                52 周位置
              </th>
              {optionalColumns.close && (
                <SortHeader
                  label="收盘"
                  column="close"
                  sort={sort}
                  onSort={onSort}
                />
              )}
              {optionalColumns.changePct && (
                <SortHeader
                  label="当日"
                  column="changePct"
                  sort={sort}
                  onSort={onSort}
                />
              )}
              {optionalColumns.pbPercentile && (
                <SortHeader
                  label="PB 分位"
                  column="pbPercentile"
                  sort={sort}
                  onSort={onSort}
                />
              )}
              {optionalColumns.riskPremium && (
                <SortHeader
                  label="风险溢价"
                  column="riskPremium"
                  sort={sort}
                  onSort={onSort}
                />
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const change = row.change_7d_pct ?? row.change_pct;
              return (
                <tr
                  key={row.index_code}
                  className="group whitespace-nowrap border-b border-border/60 transition-colors last:border-0 hover:bg-muted/30"
                >
                  <th
                    scope="row"
                    className="sticky left-0 z-10 bg-card px-3 py-2.5 text-left font-normal group-hover:bg-muted/30"
                  >
                    <Link
                      href={`/valuation/${encodeURIComponent(row.index_code)}`}
                      className="inline-flex items-center gap-1 rounded-sm font-medium text-foreground transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {row.name}
                      <ArrowUpRight
                        className="h-3 w-3 opacity-0 transition-opacity group-hover:opacity-60"
                        aria-hidden="true"
                      />
                    </Link>
                    <div className="mt-0.5 flex items-center gap-1 text-[11px] text-muted-foreground">
                      <span className="font-mono tabular-nums">
                        {row.index_code}
                      </span>
                      <span aria-hidden="true">·</span>
                      <span>{row.category}</span>
                      {row.has_etf && (
                        <>
                          <span aria-hidden="true">·</span>
                          <span className="text-primary">ETF</span>
                        </>
                      )}
                      {!row.has_valuation && (
                        <>
                          <span aria-hidden="true">·</span>
                          <span className="text-warning">仅行情</span>
                        </>
                      )}
                    </div>
                  </th>
                  <td className="px-3 py-2.5 text-right font-mono text-xs tabular-nums">
                    {formatNumber(row.pe_ttm)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-xs tabular-nums">
                    {formatNumber(row.pb)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-xs tabular-nums">
                    {formatPlainPct(row.dividend_yield_pct)}
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center justify-end gap-2">
                      <PercentileBar
                        value={row.pe_percentile}
                        showLabels={false}
                        barClassName="h-1.5"
                        className="w-16 sm:w-20"
                      />
                      <span
                        className={cn(
                          "w-11 text-right font-mono text-xs tabular-nums",
                          percentileTone(row.pe_percentile),
                        )}
                        title={
                          row.pe_percentile == null
                            ? "样本不足（需 ≥120 个交易日）"
                            : "近 5 年历史分位"
                        }
                      >
                        {formatPercentile(row.pe_percentile, 1)}
                      </span>
                    </div>
                  </td>
                  <td
                    className={cn(
                      "px-3 py-2.5 text-right font-mono text-xs tabular-nums",
                      changeClass(change),
                    )}
                  >
                    {formatSignedPct(change)}
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center justify-end gap-2">
                      <div
                        className="relative h-1.5 w-16 overflow-hidden rounded-full bg-muted sm:w-20"
                        title={
                          row.high_52w != null && row.low_52w != null
                            ? `52 周区间 ${formatNumber(row.low_52w)} ~ ${formatNumber(row.high_52w)}`
                            : "52 周区间数据不足"
                        }
                      >
                        <div
                          className="absolute inset-y-0 left-0 rounded-full bg-primary/70"
                          style={{
                            width: `${Math.max(
                              0,
                              Math.min(100, row.position_52w_pct ?? 0),
                            )}%`,
                          }}
                        />
                      </div>
                      <span className="w-10 text-right font-mono text-xs tabular-nums text-muted-foreground">
                        {row.position_52w_pct == null
                          ? "—"
                          : `${row.position_52w_pct.toFixed(0)}%`}
                      </span>
                    </div>
                  </td>
                  {optionalColumns.close && (
                    <td className="px-3 py-2.5 text-right font-mono text-xs tabular-nums">
                      {formatNumber(row.close)}
                    </td>
                  )}
                  {optionalColumns.changePct && (
                    <td
                      className={cn(
                        "px-3 py-2.5 text-right font-mono text-xs tabular-nums",
                        changeClass(row.change_pct),
                      )}
                    >
                      {formatSignedPct(row.change_pct)}
                    </td>
                  )}
                  {optionalColumns.pbPercentile && (
                    <td
                      className={cn(
                        "px-3 py-2.5 text-right font-mono text-xs tabular-nums",
                        percentileTone(row.pb_percentile),
                      )}
                    >
                      {formatPercentile(row.pb_percentile, 1)}
                    </td>
                  )}
                  {optionalColumns.riskPremium && (
                    <td className="px-3 py-2.5 text-right font-mono text-xs tabular-nums text-muted-foreground">
                      {formatSignedPct(row.risk_premium_pct)}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Surface>
  );
}

export interface ValuationHomeProps {
  /** 服务端注入的真实数据；缺失时显示空态（绝不回退示例数据）。 */
  rows?: ReadonlyArray<IndexQuoteRow>;
  cards?: ReadonlyArray<MarketValuationCard>;
  asOf?: string;
  isLive?: boolean;
}

export function ValuationHome({
  rows = [],
  cards = [],
  asOf = "—",
  isLive = true,
}: ValuationHomeProps = {}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<IndexCategoryFilter>("all");
  const [hasEtfOnly, setHasEtfOnly] = useState(false);
  const [valuationOnly, setValuationOnly] = useState(false);
  const [sort, setSort] = useState<SortState>(null);
  const [optionalColumns, setOptionalColumns] = useState(
    DEFAULT_OPTIONAL_COLUMNS,
  );

  const marketCards = useMemo(
    () =>
      [...cards]
        .sort((a, b) => boardRank(a.board) - boardRank(b.board))
        .slice(0, 5),
    [cards],
  );

  const filteredRows = useMemo(
    () =>
      filterIndexRows(rows, {
        query,
        category,
        hasEtfOnly,
        valuationOnly,
      }),
    [rows, query, category, hasEtfOnly, valuationOnly],
  );

  const visibleRows = useMemo(() => {
    if (!sort) return filteredRows;
    return [...filteredRows].sort((a, b) =>
      compareRows(a, b, sort.key, sort.direction),
    );
  }, [filteredRows, sort]);

  const hasActiveFilters =
    query.trim() !== "" ||
    category !== "all" ||
    hasEtfOnly ||
    valuationOnly;

  const resetFilters = () => {
    setQuery("");
    setCategory("all");
    setHasEtfOnly(false);
    setValuationOnly(false);
  };

  const handleSort = (key: SortKey) => {
    setSort((previous) => {
      if (!previous || previous.key !== key) {
        return { key, direction: "asc" };
      }
      if (previous.direction === "asc") {
        return { key, direction: "desc" };
      }
      return null;
    });
  };

  const toggleOptionalColumn = (key: OptionalColumnKey) => {
    setOptionalColumns((previous) => ({
      ...previous,
      [key]: !previous[key],
    }));
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="mx-auto w-full max-w-[1440px] px-4 pb-5 pt-7 sm:px-6 sm:pb-6 sm:pt-9 lg:px-8">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
              指数估值
            </h1>
            <p className="mt-1 text-xs text-muted-foreground sm:text-sm">
              PE / PB 分位、股息率与风险溢价 · 数据截至{" "}
              <span className="tabular-nums text-foreground/80">{asOf}</span>
            </p>
          </div>
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <span className="tabular-nums">
              {formatNumber(rows.length, 0)} 只指数
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1440px] space-y-6 px-4 pb-16 sm:px-6 lg:px-8">
        {rows.length === 0 && (
          <div className="rounded-xl border border-dashed border-border bg-card px-4 py-10 text-center text-sm text-muted-foreground">
            暂无估值数据，请稍后刷新
          </div>
        )}
        <section aria-labelledby="market-valuation-heading">
          <SectionHeading
            id="market-valuation-heading"
            title="全市场估值"
            hint="等权中位数"
          />
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {marketCards.map((card) => (
              <MarketCard key={card.board} card={card} />
            ))}
          </div>
        </section>

        <section
          aria-label="估值分布与横向比较"
          className="grid grid-cols-1 gap-4 md:grid-cols-2"
        >
          <PercentileHistogramCard rows={rows} />
          <PeDividendScatterCard rows={rows} />
        </section>

        <section aria-labelledby="index-table-heading">
          <SectionHeading
            id="index-table-heading"
            title="指数列表"
            hint={
              hasActiveFilters
                ? `${visibleRows.length} / ${rows.length} 只`
                : `共 ${rows.length} 只`
            }
          />

          <div className="mb-3 flex flex-wrap items-center gap-2">
            <div className="relative w-full sm:w-56">
              <Search
                className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索名称 / 代码"
                aria-label="搜索指数名称或代码"
                className="h-8 pl-8 text-xs"
              />
            </div>

            <div className="max-w-full overflow-x-auto">
              <Tabs
                value={category}
                onValueChange={(value) =>
                  setCategory(value as IndexCategoryFilter)
                }
              >
                <TabsList className="h-8" aria-label="按类别筛选指数">
                  {CATEGORY_OPTIONS.map((option) => (
                    <TabsTrigger
                      key={option.value}
                      value={option.value}
                      className="h-6 px-2.5 text-xs"
                    >
                      {option.label}
                    </TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>
            </div>

            <Button
              type="button"
              size="sm"
              variant={hasEtfOnly ? "default" : "outline"}
              aria-pressed={hasEtfOnly}
              onClick={() => setHasEtfOnly((value) => !value)}
              className="h-8 px-2.5 text-xs"
            >
              有 ETF
            </Button>
            <Button
              type="button"
              size="sm"
              variant={valuationOnly ? "default" : "outline"}
              aria-pressed={valuationOnly}
              onClick={() => setValuationOnly((value) => !value)}
              className="h-8 px-2.5 text-xs"
            >
              仅估值
            </Button>

            <div className="ml-auto flex items-center gap-2">
              {hasActiveFilters && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={resetFilters}
                  className="h-8 px-2 text-xs text-muted-foreground"
                >
                  <X className="mr-1 h-3.5 w-3.5" aria-hidden="true" />
                  清除
                </Button>
              )}

              <Popover>
                <PopoverTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 gap-1.5 px-2.5 text-xs"
                  >
                    <SlidersHorizontal
                      className="h-3.5 w-3.5"
                      aria-hidden="true"
                    />
                    列设置
                  </Button>
                </PopoverTrigger>
                <PopoverContent align="end" className="w-48 p-2">
                  <div className="px-2 py-1 text-[11px] font-medium text-muted-foreground">
                    显示列
                  </div>
                  {OPTIONAL_COLUMNS.map((column) => (
                    <label
                      key={column.key}
                      className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-xs transition-colors hover:bg-muted"
                    >
                      <Checkbox
                        checked={optionalColumns[column.key]}
                        onCheckedChange={() =>
                          toggleOptionalColumn(column.key)
                        }
                        aria-label={`显示${column.label}列`}
                      />
                      {column.label}
                    </label>
                  ))}
                </PopoverContent>
              </Popover>
            </div>
          </div>

          {visibleRows.length > 0 ? (
            <IndexTable
              rows={visibleRows}
              sort={sort}
              onSort={handleSort}
              optionalColumns={optionalColumns}
            />
          ) : (
            <Surface className="flex flex-col items-center justify-center px-6 py-12 text-center">
              <p className="text-sm font-medium">没有匹配的指数</p>
              <p className="mt-1 text-xs text-muted-foreground">
                调整筛选条件或清空搜索关键词。
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={resetFilters}
                className="mt-4 h-8 text-xs"
              >
                清除筛选
              </Button>
            </Surface>
          )}
        </section>
      </main>
    </div>
  );
}
