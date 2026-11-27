"use client";

/**
 * MVI 展开图（需求 6）：modal 双轴图。
 * - 左轴 MVI（周频、0~100），右轴指数点位（bfq 收盘）；
 * - 4 只指数可切换（默认中证全指），不同颜色、自适应宽度、hover 十字线 tooltip；
 * - 指数点位数据缺失时保留 MVI 曲线并明确提示「数据建设中」，不伪造点位。
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "next-themes";
import { RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EChart } from "@/components/EChart";
import { getChartTheme } from "@/lib/chart-theme";
import { buildMviOverlayOption } from "@/lib/valuation-chart-model";
import {
  DEFAULT_MVI_OVERLAY_INDEX,
  MVI_OVERLAY_INDEX_OPTIONS,
  fetchMviOverlay,
  type MviOverlay,
} from "@/lib/valuation-snapshot";
import type { MviInfo } from "@/lib/valuation-types";
import { cn } from "@/lib/utils";
import { ChartSkeleton, DataEmptyState } from "./valuation-ui";

export function MviOverlayModal({
  open,
  onOpenChange,
  mvi,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mvi: MviInfo | null;
}) {
  const { resolvedTheme } = useTheme();
  const theme = getChartTheme(resolvedTheme === "dark");
  const [indexCode, setIndexCode] = useState<string>(DEFAULT_MVI_OVERLAY_INDEX);
  const [overlay, setOverlay] = useState<MviOverlay | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryTick, setRetryTick] = useState(0);
  const cacheRef = useRef(new Map<string, MviOverlay | null>());

  useEffect(() => {
    if (!open) return;
    if (cacheRef.current.has(indexCode)) {
      const cached = cacheRef.current.get(indexCode) ?? null;
      setOverlay(cached);
      setError(cached ? null : "该指数点位数据暂不可用");
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    void fetchMviOverlay(indexCode)
      .then((data) => {
        if (!active) return;
        cacheRef.current.set(indexCode, data);
        setOverlay(data);
        if (!data) setError("指数点位数据暂不可用，请稍后重试");
      })
      .catch(() => {
        if (!active) return;
        cacheRef.current.set(indexCode, null);
        setOverlay(null);
        setError("指数点位数据暂不可用，请稍后重试");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [open, indexCode, retryTick]);

  const indexOption =
    MVI_OVERLAY_INDEX_OPTIONS.find((item) => item.code === indexCode) ??
    MVI_OVERLAY_INDEX_OPTIONS[0];
  const indexName = overlay?.name || indexOption.name;
  const mviPoints = overlay?.mvi.length ? overlay.mvi : (mvi?.history ?? []);
  const latestMvi = mvi?.latest ?? null;
  const latestIndex = overlay?.series.length
    ? overlay.series[overlay.series.length - 1]
    : null;

  const chartOption = useMemo(
    () =>
      buildMviOverlayOption({
        mvi: mviPoints,
        indexPoints: overlay?.series ?? [],
        indexName,
        theme,
      }),
    [mviPoints, overlay, indexName, theme],
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* 宽度：DialogContent 基础类在 sm 断点有 sm:max-w-lg，会覆盖 max-w-5xl；
          这里用 sm:max-w-6xl + 90vw 让 PC 端自适应加宽（移动端仍 100%-2rem）。 */}
      <DialogContent className="w-[90vw] sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle>MVI × 指数 · 双轴图</DialogTitle>
          <DialogDescription>
            左轴 MVI（周频，0~100）· 右轴指数点位（bfq 收盘）；切换指数为本地切换，不重载页面。
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="inline-flex overflow-hidden rounded-md border border-border text-[11px]">
            {MVI_OVERLAY_INDEX_OPTIONS.map((item) => (
              <button
                key={item.code}
                type="button"
                onClick={() => setIndexCode(item.code)}
                aria-pressed={indexCode === item.code}
                className={cn(
                  "px-2.5 py-1 transition-colors",
                  indexCode === item.code
                    ? "bg-foreground text-background"
                    : "text-muted-foreground hover:bg-muted",
                )}
              >
                {item.name}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
            <span>
              MVI{" "}
              <b className="font-mono tabular-nums text-foreground">
                {latestMvi ? latestMvi.mvi.toFixed(2) : "—"}
              </b>
              {latestMvi ? " · " + (latestMvi.zone || "—") : ""}
            </span>
            <span>
              {indexName}{" "}
              <b className="font-mono tabular-nums text-foreground">
                {latestIndex ? latestIndex.close.toLocaleString("zh-CN", { maximumFractionDigits: 2 }) : "—"}
              </b>
              {latestIndex ? " · " + latestIndex.date : ""}
            </span>
          </div>
        </div>

        {overlay?.missing ? (
          <p className="rounded-md border border-warning/30 bg-warning/10 px-2.5 py-1.5 text-[11px] text-warning">
            该指数点位数据建设中，图中仅展示 MVI 曲线（双轴保留，不伪造点位）。
          </p>
        ) : null}

        <div>
          {loading ? (
            <ChartSkeleton height={380} label="MVI 双轴图加载中" />
          ) : error && !overlay ? (
            <div className="space-y-2">
              <DataEmptyState title="指数点位数据加载失败" description={error} />
              <div className="flex justify-center">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs"
                  onClick={() => {
                    cacheRef.current.delete(indexCode);
                    setRetryTick((tick) => tick + 1);
                  }}
                >
                  <RotateCcw className="mr-1 size-3" />
                  重试
                </Button>
              </div>
            </div>
          ) : (
            <EChart option={chartOption} style={{ height: 380, width: "100%" }} />
          )}
        </div>

        <p className="text-[10px] leading-relaxed text-muted-foreground">
          口径：MVI 为周频序列（ISO 周去重，104 周滚动分位）；指数点位来自 bp_index_quote_daily（bfq，原币）。
          MVI 最新 {latestMvi?.as_of ?? "—"} · 点位截至 {latestIndex?.date ?? "—"}。
        </p>
      </DialogContent>
    </Dialog>
  );
}
