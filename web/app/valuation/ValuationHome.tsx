"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Search, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import type {
  IndexQuoteRow,
  MarketValuationCard,
  ValuationLevel,
} from "@/lib/valuation-types";
import {
  MOCK_BROAD_INDEX_ROWS,
  MOCK_INDEX_ROWS,
  MOCK_MARKET_CARDS,
  VALUATION_AS_OF,
  changeClass,
  filterIndexRows,
  formatNumber,
  formatPercentile,
  formatPlainPct,
  formatSignedPct,
  levelClass,
  percentileClass,
  type IndexCategoryFilter,
} from "@/lib/valuation-mock";

// 涨跌方向色只走 changeClass 返回的 text-up / text-down；估值分位色走
// success / warning / destructive，两者互不混用。
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

const LEVEL_BADGE_BG: Record<ValuationLevel, string> = {
  低估: "border-success/30 bg-success/10",
  中性: "border-warning/30 bg-warning/10",
  高估: "border-destructive/30 bg-destructive/10",
};

function LevelBadge({ level }: { level: ValuationLevel | null }) {
  if (!level) {
    return (
      <span className="inline-flex items-center rounded-full border border-border bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
        样本不足
      </span>
    );
  }
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
        levelClass(level),
        LEVEL_BADGE_BG[level],
      )}
    >
      {level}
    </span>
  );
}

/**
 * 0~1 分位的迷你刻度条。低分位在左侧、高分位在右侧，给卡片里的百分比一个
 * 不依赖颜色的第二编码；缺失时明确显示「分位样本积累中」。
 */
function PercentileMeter({ value }: { value: number | null }) {
  if (value == null) {
    return (
      <div className="mt-2">
        <div className="h-1.5 w-full rounded-full bg-muted" aria-hidden="true" />
        <div className="mt-1 text-[10px] text-muted-foreground">
          分位样本积累中
        </div>
      </div>
    );
  }

  const width = Math.min(100, Math.max(0, value));
  return (
    <div className="mt-2">
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
        aria-hidden="true"
      >
        <div
          className="h-full rounded-full bg-primary"
          style={{ width: `${width}%` }}
        />
      </div>
      <div
        className="mt-1 flex items-center justify-between text-[10px] tabular-nums text-muted-foreground"
        aria-hidden="true"
      >
        <span>0%</span>
        <span>50%</span>
        <span>100%</span>
      </div>
    </div>
  );
}

function MarketCard({ card }: { card: MarketValuationCard }) {
  return (
    <Card className="border-border/60 bg-card/60 shadow-none transition-colors hover:border-primary/30">
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold tracking-tight">{card.label}</h3>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              {card.board === "all" ? "全 A 股等权中位数" : "板块等权中位数"}
            </p>
          </div>
          <LevelBadge level={card.level} />
        </div>

        <div className="mt-4 grid grid-cols-2 gap-4">
          <div>
            <div className="text-[11px] text-muted-foreground">PE (TTM)</div>
            <div className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">
              {formatNumber(card.pe)}
            </div>
            <PercentileMeter value={card.pe_percentile} />
            <div
              className={cn(
                "mt-1.5 text-xs tabular-nums",
                percentileClass(card.pe_percentile),
              )}
            >
              分位 {formatPercentile(card.pe_percentile)}
            </div>
          </div>
          <div>
            <div className="text-[11px] text-muted-foreground">PB</div>
            <div className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">
              {formatNumber(card.pb)}
            </div>
            <PercentileMeter value={card.pb_percentile} />
            <div
              className={cn(
                "mt-1.5 text-xs tabular-nums",
                percentileClass(card.pb_percentile),
              )}
            >
              分位 {formatPercentile(card.pb_percentile)}
            </div>
          </div>
        </div>

        {card.history_days < 120 && (
          <p className="mt-3 text-[11px] leading-relaxed tabular-nums text-warning">
            历史归档积累中（已 {card.history_days} 天，分位样本需 120 天）
          </p>
        )}

        <div className="mt-4 flex items-center justify-between border-t border-border/60 pt-3 text-[11px] text-muted-foreground">
          <span>样本 {formatNumber(card.sample_size, 0)}</span>
          <span>截至 {card.as_of}</span>
        </div>
      </CardContent>
    </Card>
  );
}

function SectionHeading({
  id,
  title,
  hint,
}: {
  id: string;
  title: string;
  hint?: string;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
      <h2
        id={id}
        className="flex items-center gap-2 text-lg font-semibold tracking-tight"
      >
        <span
          className="h-4 w-[3px] shrink-0 rounded-full bg-primary"
          aria-hidden="true"
        />
        {title}
      </h2>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function IndexTable({
  rows,
  caption,
  showMeta = false,
}: {
  rows: readonly IndexQuoteRow[];
  caption: string;
  showMeta?: boolean;
}) {
  return (
    <div className="overflow-x-auto overscroll-x-contain rounded-xl border border-border bg-card">
      <table className="w-full min-w-[1140px] border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="whitespace-nowrap border-b border-border bg-muted/40 text-[11px] text-muted-foreground">
            <th
              scope="col"
              className="sticky left-0 z-10 bg-muted/40 px-4 py-3 text-left font-medium"
            >
              指数
            </th>
            <th scope="col" className="px-3 py-3 text-right font-medium">
              收盘
            </th>
            <th scope="col" className="px-3 py-3 text-right font-medium">
              当日
            </th>
            <th scope="col" className="px-3 py-3 text-right font-medium">
              52 周
            </th>
            <th scope="col" className="px-3 py-3 text-right font-medium">
              距最高
            </th>
            <th
              scope="col"
              className="px-3 py-3 text-right font-medium"
              title="滚动 12 个月市盈率"
            >
              PE (TTM)
            </th>
            <th
              scope="col"
              className="px-3 py-3 text-right font-medium"
              title="近 5 年历史分位"
            >
              PE 分位
            </th>
            <th scope="col" className="px-3 py-3 text-right font-medium">
              PB
            </th>
            <th
              scope="col"
              className="px-3 py-3 text-right font-medium"
              title="近 5 年历史分位"
            >
              PB 分位
            </th>
            <th scope="col" className="px-3 py-3 text-right font-medium">
              股息率
            </th>
            <th
              scope="col"
              className="px-3 py-3 text-right font-medium"
              title="股息率 TTM − 十年期国债收益率"
            >
              风险溢价
            </th>
            <th scope="col" className="px-3 py-3 text-right font-medium">
              详情
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.index_code}
              className="group whitespace-nowrap border-b border-border/60 transition-colors last:border-0 hover:bg-muted/30"
            >
              <th
                scope="row"
                className="sticky left-0 z-10 bg-card px-4 py-3 text-left font-normal group-hover:bg-muted/30"
              >
                <div className="flex min-w-[180px] flex-col gap-1">
                  <span className="font-medium text-foreground">{row.name}</span>
                  <span className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                    <span className="font-mono tabular-nums">
                      {row.index_code}
                    </span>
                    <span className="rounded border border-border px-1.5 py-0.5">
                      {row.category}
                    </span>
                    {showMeta && row.has_etf && (
                      <span className="rounded border border-primary/20 bg-primary/5 px-1.5 py-0.5 text-primary">
                        ETF
                      </span>
                    )}
                    {showMeta && !row.has_valuation && (
                      <span className="rounded border border-warning/30 bg-warning/10 px-1.5 py-0.5 text-warning">
                        仅行情
                      </span>
                    )}
                  </span>
                </div>
              </th>
              <td className="px-3 py-3 text-right tabular-nums">
                {formatNumber(row.close)}
              </td>
              <td
                className={cn(
                  "px-3 py-3 text-right tabular-nums",
                  changeClass(row.change_pct),
                )}
              >
                {formatSignedPct(row.change_pct)}
              </td>
              <td
                className={cn(
                  "px-3 py-3 text-right tabular-nums",
                  changeClass(row.change_52w_pct),
                )}
              >
                {formatSignedPct(row.change_52w_pct)}
              </td>
              <td className="px-3 py-3 text-right tabular-nums text-muted-foreground">
                {formatSignedPct(row.distance_from_high_pct)}
              </td>
              <td className="px-3 py-3 text-right tabular-nums">
                {formatNumber(row.pe_ttm)}
              </td>
              <td
                className={cn(
                  "px-3 py-3 text-right tabular-nums",
                  percentileClass(row.pe_percentile),
                )}
                title={
                  row.pe_percentile == null
                    ? "样本不足（需 ≥120 个交易日）"
                    : "近 5 年历史分位"
                }
              >
                {formatPercentile(row.pe_percentile)}
              </td>
              <td className="px-3 py-3 text-right tabular-nums">
                {formatNumber(row.pb)}
              </td>
              <td
                className={cn(
                  "px-3 py-3 text-right tabular-nums",
                  percentileClass(row.pb_percentile),
                )}
                title={
                  row.pb_percentile == null
                    ? "样本不足（需 ≥120 个交易日）"
                    : "近 5 年历史分位"
                }
              >
                {formatPercentile(row.pb_percentile)}
              </td>
              <td className="px-3 py-3 text-right tabular-nums">
                {formatPlainPct(row.dividend_yield_pct)}
              </td>
              <td className="px-3 py-3 text-right tabular-nums text-muted-foreground">
                {formatSignedPct(row.risk_premium_pct)}
              </td>
              <td className="px-3 py-3 text-right">
                <Link
                  href={"/valuation/" + row.index_code}
                  className="inline-flex items-center rounded-md border border-border px-2 py-1 text-xs text-primary transition-colors hover:bg-primary/5"
                  aria-label={`查看 ${row.name} 详情`}
                >
                  详情
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export interface ValuationHomeProps {
  /** 服务端注入的真实数据；缺省时回退到 mock 示例。 */
  rows?: ReadonlyArray<IndexQuoteRow>;
  cards?: ReadonlyArray<MarketValuationCard>;
  broadRows?: ReadonlyArray<IndexQuoteRow>;
  asOf?: string;
  isLive?: boolean;
}

export function ValuationHome({
  rows = MOCK_INDEX_ROWS,
  cards = MOCK_MARKET_CARDS,
  broadRows = MOCK_BROAD_INDEX_ROWS,
  asOf = VALUATION_AS_OF,
  isLive = false,
}: ValuationHomeProps = {}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<IndexCategoryFilter>("all");
  const [hasEtfOnly, setHasEtfOnly] = useState(false);
  const [valuationOnly, setValuationOnly] = useState(false);

  const filteredRows = useMemo(
    () =>
      filterIndexRows(rows, {
        query,
        category,
        hasEtfOnly,
        valuationOnly,
      }),
    [query, category, hasEtfOnly, valuationOnly],
  );

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

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border/60 bg-card/30">
        <div className="mx-auto w-full max-w-[1240px] px-4 py-7 sm:px-6 sm:py-8">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <Badge
                  variant="outline"
                  className="border-primary/30 bg-primary/5 text-primary"
                >
                  指数估值
                </Badge>
                <span className="text-xs text-muted-foreground">
                  Mock 示例 · 尚未接入 API
                </span>
              </div>
              <h1 className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">
                指数估值
              </h1>
              <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
                用 PE / PB 历史分位、股息率与风险溢价，判断宽基与行业指数的相对贵贱。
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline" className="tabular-nums">
                {rows.length} 只{isLive ? "指数" : "示例指数"}
              </Badge>
              <Badge variant="outline" className="tabular-nums">
                数据截至 {asOf}{isLive ? null : " · 示例数据"}
              </Badge>
              <Badge variant="outline" className="tabular-nums">
                每日 21:00 更新
              </Badge>
            </div>
          </div>

          <p className="mt-5 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-xs leading-relaxed text-foreground">
            <span className="font-medium text-primary">页面骨架：</span>
            当前卡片与表格使用 mock 数据，用于确认布局、筛选与数字口径；接入估值预计算表后替换数据源。
          </p>
        </div>
      </header>

      <div className="mx-auto w-full max-w-[1240px] px-4 py-6 sm:px-6 sm:py-8">
        <div className="space-y-10">
          {/* 1. 全市场估值：4 张板块卡 */}
          <section aria-labelledby="market-valuation-heading">
            <SectionHeading
              id="market-valuation-heading"
              title="全市场估值"
              hint="全 A 股等权中位数 · 分位自 2015 年起"
            />
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {cards.map((card) => (
                <MarketCard key={card.board} card={card} />
              ))}
            </div>
          </section>

          {/* 2. 宽基指数：固定 8 行 */}
          <section aria-labelledby="broad-index-heading">
            <SectionHeading
              id="broad-index-heading"
              title="宽基指数"
              hint="8 只核心指数（含中证红利）· 收盘 / 涨跌 / 52 周 / 距最高 / PE / PB / 股息率 / 风险溢价"
            />
            <IndexTable
              rows={broadRows}
              caption="核心宽基指数估值表，共 8 行"
            />
          </section>

          {/* 3. 全部指数：类别 / 有ETF / 仅估值 + 搜索 */}
          <section aria-labelledby="all-index-heading">
            <SectionHeading
              id="all-index-heading"
              title="全部指数估值"
              hint={isLive ? undefined : "接入后展示全量 521 只；当前为 " + rows.length + " 只示例"}
            />

            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="shrink-0 text-xs text-muted-foreground">
                    类别
                  </span>
                  <div className="max-w-full overflow-x-auto">
                    <Tabs
                      value={category}
                      onValueChange={(value) =>
                        setCategory(value as IndexCategoryFilter)
                      }
                    >
                      <TabsList className="h-9" aria-label="按类别筛选指数">
                        {CATEGORY_OPTIONS.map((option) => (
                          <TabsTrigger
                            key={option.value}
                            value={option.value}
                            className="h-7 px-3 text-xs"
                          >
                            {option.label}
                          </TabsTrigger>
                        ))}
                      </TabsList>
                    </Tabs>
                  </div>
                </div>

                <Button
                  type="button"
                  size="sm"
                  variant={hasEtfOnly ? "default" : "outline"}
                  aria-pressed={hasEtfOnly}
                  onClick={() => setHasEtfOnly((value) => !value)}
                >
                  有ETF
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={valuationOnly ? "default" : "outline"}
                  aria-pressed={valuationOnly}
                  onClick={() => setValuationOnly((value) => !value)}
                >
                  仅估值
                </Button>

                <div className="relative w-full sm:ml-auto sm:w-64">
                  <Search
                    className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                    aria-hidden="true"
                  />
                  <Input
                    type="search"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="搜索名称 / 代码"
                    aria-label="搜索指数名称或代码"
                    className="h-9 pl-8"
                  />
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                <span aria-live="polite">
                  共{" "}
                  <span className="font-medium tabular-nums text-foreground">
                    {filteredRows.length}
                  </span>{" "}
                  只 · {isLive ? "实时" : "示例"}数据 {rows.length} 只
                </span>
                {hasActiveFilters && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={resetFilters}
                    className="h-7 px-2 text-xs text-muted-foreground"
                  >
                    <X className="mr-1 h-3.5 w-3.5" aria-hidden="true" />
                    清除筛选
                  </Button>
                )}
              </div>
            </div>

            <div className="mt-3">
              {filteredRows.length > 0 ? (
                <IndexTable
                  rows={filteredRows}
                  caption="全部指数估值表，可按类别、ETF 与估值覆盖筛选"
                  showMeta
                />
              ) : (
                <div className="rounded-xl border border-dashed border-border bg-card px-6 py-12 text-center">
                  <p className="text-sm font-medium">没有匹配的指数</p>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                    试试调整类别、ETF 或估值筛选，或清空搜索关键词。
                  </p>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={resetFilters}
                    className="mt-4"
                  >
                    清除筛选
                  </Button>
                </div>
              )}
            </div>
          </section>
        </div>

        <p className="mt-10 text-[11px] leading-relaxed text-muted-foreground">
          口径：指数表的 PE/PB 分位为近 5 年历史分位，全市场卡片分位自 2015 年起；
          风险溢价 = 股息率 TTM − 十年期国债收益率（同日）。缺失或样本不足显示「—」，
          不以 0 代替。当前为 mock 数据，不构成投资建议。
        </p>
      </div>
    </div>
  );
}
