"use client";

import { useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { EChart } from "@/components/EChart";
import { ChartLightbox } from "@/components/ChartLightbox";
import { useIsMobile } from "@/components/ui/use-mobile";
import { type ChartTheme } from "@/lib/chart-theme";

type MatrixAsset = { index: number; label: string; category: string };

const CATEGORY_LABEL: Record<string, string> = {
  index: "指数",
  etf: "ETF",
  bond: "债券",
  commodity: "商品",
  other: "其他",
};

function seededRandom(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0xffffffff;
  };
}

function inferCategory(label: string, source?: string): string {
  if (source?.includes("etf")) return "etf";
  if (/债|国债|政金|利率/.test(label)) return "bond";
  if (/商品|原油|豆粕|有色|能化|黄金|白银/.test(label)) return "commodity";
  return "index";
}

/**
 * 默认选中：组合当前成分 + 持仓权重优先 + 跨资产类别多样化，上限 limit。
 * 1) 每个类别先放入其最高权重的一只，保证不同类型资产都有；
 * 2) 剩余名额按权重全局降序补足；
 * 3) 权重并列/缺失时用 portfolioId 种子稳定打散。
 */
function pickDiverseDefault(
  assets: MatrixAsset[],
  weightByIndex: Map<number, number>,
  limit: number,
  seed: number,
): Set<number> {
  if (assets.length <= limit) return new Set(assets.map((a) => a.index));
  const rng = seededRandom(seed);
  const jitter = new Map<number, number>(assets.map((a) => [a.index, rng()]));
  const weight = (i: number) => weightByIndex.get(i) ?? 0;
  const cmp = (a: MatrixAsset, b: MatrixAsset) =>
    weight(b.index) - weight(a.index) || (jitter.get(a.index)! - jitter.get(b.index)!);

  const byCat = new Map<string, MatrixAsset[]>();
  for (const a of assets) {
    const cat = a.category || "other";
    if (!byCat.has(cat)) byCat.set(cat, []);
    byCat.get(cat)!.push(a);
  }
  for (const arr of byCat.values()) arr.sort(cmp);

  const selected: number[] = [];
  // 第一轮: 每类取权重最高的一只(类别顺序按其头部权重降序)
  const cats = [...byCat.entries()].sort((x, y) => cmp(x[1][0], y[1][0]));
  for (const [, arr] of cats) {
    if (selected.length >= limit) break;
    selected.push(arr[0].index);
  }
  // 第二轮: 剩余资产按权重全局降序补足
  const rest = assets
    .filter((a) => !selected.includes(a.index))
    .sort(cmp);
  for (const a of rest) {
    if (selected.length >= limit) break;
    selected.push(a.index);
  }
  return new Set(selected);
}

function shortLabel(name: string, mobile: boolean): string {
  if (!mobile) return name;
  const base = name.split("(")[0].trim();
  return base.length > 8 ? `${base.slice(0, 7)}…` : base;
}

/** 将较长品种名按字符数折行, 供 axisLabel.formatter 用; 灯箱(宽屏)场景避免标签截断。
    CJK 与数字混排下约每 6 字符一换行, 与 ECharts 自带 width+overflow 配合。 */
function wrapLabel(name: string, max = 6): string {
  if (name.length <= max) return name;
  const parts: string[] = [];
  for (let i = 0; i < name.length; i += max) parts.push(name.slice(i, i + max));
  return parts.join("\n");
}

function subMatrix(matrix: number[][], indices: number[]): number[][] {
  return indices.map((i) => indices.map((j) => matrix[i]?.[j] ?? 0));
}

/** 以 0 为中心的对称色标上界（ColorBrewer RdBu / coolwarm 惯例） */
function symmetricZeroBounds(matrix: number[][]): { min: number; max: number; absMax: number } {
  let absMax = 0;
  matrix.forEach((row) => row.forEach((v) => {
    absMax = Math.max(absMax, Math.abs(v));
  }));
  if (absMax < 1e-12) absMax = 1e-6;
  return { min: -absMax, max: absMax, absMax };
}

function decimalsForMagnitude(absMax: number): number {
  if (absMax >= 0.1) return 2;
  if (absMax >= 0.01) return 3;
  if (absMax >= 0.001) return 4;
  return 5;
}

/** 协方差矩阵：5 阶 RdBu 发散色，0 为中性灰，负蓝 / 正红（取自主题 9 阶 rdBu 的 0/2/4/6/8） */
function covDivergingColors(theme: ChartTheme): string[] {
  const r = theme.rdBu;
  return [r[0], r[2], r[4], r[6], r[8]];
}

function formatMapLabel(v: number, decimals: number): string {
  if (Math.abs(v) < 10 ** -(decimals + 1)) return "0";
  return v.toFixed(decimals);
}

function buildHeatmapOption(
  labels: string[],
  matrix: number[][],
  opts: {
    theme: ChartTheme;
    isMobile: boolean;
    min: number;
    max: number;
    valueName: string;
    format: (v: number) => string;
    colors: string[];
    mapDecimals?: number;
    labelDecimals?: number;
    /** 灯箱全屏模式: 标签换行展示完整品种名, 不加挤。 */
    wide?: boolean;
  },
) {
  const { theme } = opts;
  const displayLabels = labels.map((l) => shortLabel(l, opts.isMobile));
  const height = opts.isMobile ? Math.max(320, labels.length * 28) : Math.max(360, labels.length * 22);
  const mapDecimals = opts.mapDecimals ?? 2;
  const labelDecimals = opts.labelDecimals ?? (opts.valueName === "相关系数" ? 2 : 4);
  // 灯箱(宽屏): 标签换行, 纵向不旋转(横坐标旋转45°), 避免居中留白过大
  const xLabel = opts.wide
    ? { color: theme.subtext, rotate: 45, fontSize: 11, interval: 0, width: 96, overflow: "break", formatter: (s: string) => wrapLabel(s) }
    : { color: theme.subtext, rotate: 45, fontSize: opts.isMobile ? 8 : 10, width: opts.isMobile ? 36 : 80, overflow: "truncate" };
  const yLabel = opts.wide
    ? { color: theme.subtext, fontSize: 11, width: 110, overflow: "break", formatter: (s: string) => wrapLabel(s, 7) }
    : { color: theme.subtext, fontSize: opts.isMobile ? 8 : 10, width: opts.isMobile ? 36 : 92, overflow: "break" };
  return {
    height,
    option: {
      tooltip: {
        position: "top",
        appendToBody: true,
        confine: true,
        backgroundColor: theme.tooltipBg,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.text },
        extraCssText: "z-index: 99999; box-shadow: 0 4px 16px rgba(0,0,0,0.18);",
        formatter: (p: { value: [number, number, number] }) =>
          `${labels[p.value[1]]} × ${labels[p.value[0]]}<br/>${opts.valueName}: ${opts.format(p.value[2])}`,
      },
      grid: {
        top: 10,
        bottom: opts.isMobile ? 72 : 90,
        left: opts.isMobile ? 48 : opts.wide ? 8 : 90,
        right: opts.isMobile ? 8 : opts.wide ? 8 : 20,
        containLabel: true,
      },
      xAxis: {
        type: "category",
        data: displayLabels,
        axisLabel: xLabel,
        splitArea: { show: true },
      },
      yAxis: {
        type: "category",
        data: displayLabels,
        axisLabel: yLabel,
        splitArea: { show: true },
      },
      visualMap: {
        min: opts.min,
        max: opts.max,
        calculable: true,
        precision: mapDecimals,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        inRange: { color: opts.colors },
        textStyle: { color: theme.subtext },
        formatter: (v: number) => formatMapLabel(v, mapDecimals),
      },
      series: [{
        type: "heatmap",
        data: matrix.flatMap((row, i) =>
          row.map((v, j) => [j, i, v]),
        ),
        label: {
          show: !opts.isMobile && labels.length <= 8,
          color: theme.text,
          fontSize: 9,
          formatter: (p: { value: [number, number, number] }) => {
            const val = p.value[2];
            if (Math.abs(val) < 10 ** -(labelDecimals + 1)) return "0";
            return val.toFixed(labelDecimals);
          },
        },
        emphasis: { itemStyle: { shadowBlur: 8, shadowColor: "rgba(0,0,0,0.3)" } },
      }],
    },
  };
}

const DEFAULT_LIMIT = 15;

export function RiskMatrixSection({
  corr,
  portfolioId,
  portfolioAssets,
  holdings,
  lookbackDays,
  theme,
}: {
  corr: { labels: string[]; matrix: number[][]; cov?: number[][] };
  portfolioId: number;
  portfolioAssets?: Array<{ symbol: string; source: string; display_name?: string }>;
  holdings?: Array<{ key?: string; name?: string; weight: number }>;
  lookbackDays: number;
  theme: ChartTheme;
}) {
  const isMobile = useIsMobile();

  const matrixAssets = useMemo((): MatrixAsset[] => {
    const labelToMeta = new Map<string, { source?: string }>();
    (portfolioAssets || []).forEach((a) => {
      const label = a.display_name || a.symbol;
      labelToMeta.set(label, { source: a.source });
    });
    return corr.labels.map((label, index) => ({
      index,
      label,
      category: inferCategory(label, labelToMeta.get(label)?.source),
    }));
  }, [corr.labels, portfolioAssets]);

  // 标签 → 持仓权重(优先按 name 匹配 corr.labels)
  const weightByIndex = useMemo(() => {
    const byName = new Map<string, number>();
    (holdings || []).forEach((h) => {
      if (h.name) byName.set(h.name, h.weight);
    });
    const m = new Map<number, number>();
    corr.labels.forEach((label, i) => m.set(i, byName.get(label) ?? 0));
    return m;
  }, [holdings, corr.labels]);

  const defaultSelected = useMemo(
    () => pickDiverseDefault(matrixAssets, weightByIndex, DEFAULT_LIMIT, portfolioId * 2654435761),
    [matrixAssets, weightByIndex, portfolioId],
  );

  const [selected, setSelected] = useState<Set<number>>(defaultSelected);

  useEffect(() => {
    setSelected(defaultSelected);
  }, [defaultSelected, portfolioId]);

  const selectedIndices = useMemo(
    () => [...selected].sort((a, b) => a - b),
    [selected],
  );

  const selectedLabels = useMemo(
    () => selectedIndices.map((i) => corr.labels[i]),
    [selectedIndices, corr.labels],
  );

  const corrSub = useMemo(
    () => subMatrix(corr.matrix, selectedIndices),
    [corr.matrix, selectedIndices],
  );

  const covFull = corr.cov && corr.cov.length > 0 ? corr.cov : [];
  const covSub = useMemo(
    () => (covFull.length ? subMatrix(covFull, selectedIndices) : []),
    [covFull, selectedIndices],
  );

  const corrChart = useMemo(() => {
    if (selectedIndices.length < 2) return null;
    return buildHeatmapOption(selectedLabels, corrSub, {
      theme, isMobile,
      min: -1, max: 1,
      valueName: "相关系数",
      format: (v) => v.toFixed(2),
      mapDecimals: 1,
      labelDecimals: 2,
      colors: [theme.up, theme.rdBu[4], theme.down],
    });
  }, [selectedLabels, corrSub, selectedIndices.length, theme, isMobile]);

  const covChart = useMemo(() => {
    if (selectedIndices.length < 2 || !covSub.length) return null;
    const { min, max, absMax } = symmetricZeroBounds(covSub);
    const mapDecimals = decimalsForMagnitude(absMax);
    const fmt = (v: number) => v.toFixed(mapDecimals);
    return buildHeatmapOption(selectedLabels, covSub, {
      theme, isMobile,
      min, max,
      valueName: "年化协方差",
      format: fmt,
      mapDecimals,
      labelDecimals: mapDecimals,
      colors: covDivergingColors(theme),
    });
  }, [selectedLabels, covSub, selectedIndices.length, theme, isMobile]);

  // 灯箱展示用「全量」矩阵(所有成分), 放大按钮看清全貌(与已选子集无关)。
  const allIndices = useMemo(
    () => matrixAssets.map((a) => a.index),
    [matrixAssets],
  );
  const allLabels = useMemo(() => allIndices.map((i) => corr.labels[i]), [allIndices, corr.labels]);
  const fullCorrOption = useMemo(() => {
    if (allIndices.length < 2) return null;
    return buildHeatmapOption(
      allLabels,
      subMatrix(corr.matrix, allIndices),
      {
        theme, isMobile: false,
        min: -1, max: 1,
        valueName: "相关系数", format: (v) => v.toFixed(2),
        mapDecimals: 1, labelDecimals: 2,
        colors: [theme.up, theme.rdBu[4], theme.down],
        wide: true,
      },
    ).option;
  }, [allIndices, allLabels, corr.matrix, theme]);
  const fullCovOption = useMemo(() => {
    if (allIndices.length < 2 || !covFull.length) return null;
    const full = subMatrix(covFull, allIndices);
    const { min, max, absMax } = symmetricZeroBounds(full);
    const mapDecimals = decimalsForMagnitude(absMax);
    const fmt = (v: number) => v.toFixed(mapDecimals);
    return buildHeatmapOption(
      allLabels,
      full,
      {
        theme, isMobile: false,
        min, max,
        valueName: "年化协方差", format: fmt,
        mapDecimals, labelDecimals: mapDecimals,
        colors: covDivergingColors(theme),
        wide: true,
      },
    ).option;
  }, [allIndices, allLabels, covFull, theme]);
  const fullHeight = Math.max(640, allIndices.length * 28 + 120);

  const toggle = (index: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  if (!corr.labels.length) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>相关性与协方差矩阵</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-muted-foreground py-12 text-center">无矩阵数据</div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card id="risk-matrix" className="scroll-mt-24">
      <CardHeader>
        <CardTitle>相关性与协方差矩阵</CardTitle>
        <CardDescription>
          近 {lookbackDays || 156} 个交易日日收益率（跟随组合回溯参数） · 已选 {selected.size} / {matrixAssets.length} 个成分
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="outline" size="sm" onClick={() => setSelected(new Set(matrixAssets.map((a) => a.index)))}>
            全选
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={() => setSelected(new Set())}>
            全不选
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => setSelected(new Set(defaultSelected))}>
            恢复默认
          </Button>
        </div>

        <div className="max-h-48 overflow-y-auto rounded-lg border border-border p-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {matrixAssets.map((a) => (
            <label
              key={a.index}
              className="flex items-center gap-2 text-sm cursor-pointer rounded-md px-2 py-1.5 hover:bg-muted/40"
            >
              <Checkbox
                checked={selected.has(a.index)}
                onCheckedChange={() => toggle(a.index)}
              />
              <span className="truncate flex-1 min-w-0">{a.label}</span>
              <Badge variant="secondary" className="text-[10px] shrink-0 font-normal">
                {CATEGORY_LABEL[a.category] || a.category}
              </Badge>
            </label>
          ))}
        </div>

        {selectedIndices.length < 2 ? (
          <div className="text-sm text-muted-foreground py-8 text-center border border-dashed border-border rounded-lg">
            请至少选择 2 个资产以显示矩阵
          </div>
        ) : (
          <>
            <div className="space-y-3">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <h3 className="text-sm font-medium">相关性矩阵</h3>
                  {fullCorrOption && (
                    <ChartLightbox
                      title="相关性矩阵（全量成分）"
                      description="全部成分的两两相关系数热力图。全屏下可横向滚动查看完整矩阵，标签不再截断。"
                      option={fullCorrOption}
                      label="相关性矩阵"
                      className="h-6 w-6"
                    />
                  )}
                </div>
                <p className="text-sm text-muted-foreground leading-relaxed mb-3">
                  相关系数 ∈ [-1, 1]，衡量两资产日收益同向或反向程度。接近 1 表示同涨同跌，接近 -1 表示对冲关系，接近 0 表示线性无关。
                  构建分散化组合时，宜降低高相关簇的权重叠加；但相关≠因果，危机时期相关常会同步上升。
                </p>
              </div>
              {corrChart && (
                <div className="overflow-x-auto -mx-1 px-1">
                  <div className="min-w-[280px]">
                    <EChart option={corrChart.option} style={{ height: corrChart.height, width: "100%" }} />
                  </div>
                </div>
              )}
            </div>

            <div className="space-y-3">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <h3 className="text-sm font-medium">协方差矩阵（年化）</h3>
                  {fullCovOption && (
                    <ChartLightbox
                      title="协方差矩阵（全量成分）"
                      description="全部成分的年化协方差热力图。全屏下可横向滚动查看完整矩阵。"
                      option={fullCovOption}
                      label="协方差矩阵"
                      className="h-6 w-6"
                    />
                  )}
                </div>
                <p className="text-sm text-muted-foreground leading-relaxed mb-3">
                  采用以 <strong className="text-foreground font-medium">0 为中心</strong> 的 RdBu 发散色标（量化热力图常用方案）：
                  负协方差偏蓝、正协方差偏红、接近 0 为中性灰白；色条范围对称 ±max(|值|)，两极对比清晰。
                  对角线为年化方差（恒为正，偏红）；非对角反映两资产共同波动方向与强度。
                </p>
              </div>
              {covChart ? (
                <div className="overflow-x-auto -mx-1 px-1">
                  <div className="min-w-[280px]">
                    <EChart option={covChart.option} style={{ height: covChart.height, width: "100%" }} />
                  </div>
                </div>
              ) : (
                <div className="text-sm text-muted-foreground py-8 text-center">无协方差数据</div>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
