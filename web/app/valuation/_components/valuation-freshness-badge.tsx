"use client";

/**
 * 页头全局数据更新徽标（需求 1/10）。
 *
 * - 主文案：「数据更新至 YYYY-MM-DD」（= meta.latest_complete_date）；
 * - hover / 点击展开 8 类数据明细（as_of、状态、落后天数、更新于、失败原因）；
 * - 接口未就绪时显示占位并按 3s/10s/30s/60s 退避重试，就绪后每 60s 轮询；
 * - 任一数据集落后时徽标转琥珀；全部齐套为绿点（不改变现网视觉 token）。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import {
  fetchDataFreshness,
  freshnessBadgeText,
  freshnessItemTone,
  freshnessMetaSummary,
  freshnessStatusLabel,
  freshnessTone,
  formatUpdatedAt,
  placeholderFreshness,
  type DataFreshness,
  type FreshnessStatus,
} from "@/lib/valuation-freshness";

const POLL_MS = 60_000;
const RETRY_MS = [3_000, 10_000, 30_000, 60_000] as const;

type Phase = "loading" | "ready" | "error";

const ITEM_TAG_TONE: Record<"ok" | "warning" | "muted", string> = {
  ok: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning",
  muted: "bg-muted text-muted-foreground",
};

function itemStatusText(status: FreshnessStatus): string {
  return freshnessStatusLabel(status);
}

export function DataFreshnessBadge({ className }: { className?: string }) {
  const [freshness, setFreshness] = useState<DataFreshness | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [connectionStale, setConnectionStale] = useState(false);
  const [open, setOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const closeTimer = useRef<number | null>(null);

  const apply = useCallback((data: DataFreshness | null) => {
    if (data) {
      setFreshness(data);
      setPhase("ready");
      setConnectionStale(false);
    } else {
      setConnectionStale(true);
      setPhase((previous) => (previous === "ready" ? "ready" : "error"));
    }
  }, []);

  useEffect(() => {
    let disposed = false;
    let timer: number | undefined;
    let attempt = 0;
    let controller: AbortController | null = null;

    const tick = async () => {
      controller?.abort();
      controller = new AbortController();
      const data = await fetchDataFreshness(controller.signal);
      if (disposed) return;
      apply(data);
      if (data) {
        attempt = 0;
        timer = window.setTimeout(() => void tick(), POLL_MS);
      } else {
        const delay = RETRY_MS[Math.min(attempt, RETRY_MS.length - 1)];
        attempt += 1;
        timer = window.setTimeout(() => void tick(), delay);
      }
    };

    void tick();
    return () => {
      disposed = true;
      controller?.abort();
      if (timer != null) window.clearTimeout(timer);
    };
  }, [apply]);

  const refreshNow = useCallback(async () => {
    setRefreshing(true);
    const data = await fetchDataFreshness();
    apply(data);
    setRefreshing(false);
  }, [apply]);

  const clearCloseTimer = () => {
    if (closeTimer.current != null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  };
  const openNow = () => {
    clearCloseTimer();
    setOpen(true);
  };
  const scheduleClose = () => {
    clearCloseTimer();
    closeTimer.current = window.setTimeout(() => setOpen(false), 160);
  };
  useEffect(() => () => clearCloseTimer(), []);

  const details = freshness ?? placeholderFreshness();
  const baseTone = freshnessTone(freshness);
  const tone = connectionStale && freshness ? "warning" : baseTone;
  const text =
    phase === "error" && !freshness
      ? "数据更新状态 暂不可用"
      : phase === "loading" && !freshness
        ? "数据更新状态 获取中…"
        : freshnessBadgeText(freshness);
  const dotClass =
    tone === "ok"
      ? "bg-success"
      : tone === "warning"
        ? "bg-warning"
        : "bg-muted-foreground animate-pulse";

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={text + "，查看 8 类数据明细"}
          aria-expanded={open}
          onMouseEnter={openNow}
          onMouseLeave={scheduleClose}
          onFocus={openNow}
          onBlur={scheduleClose}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            className,
          )}
        >
          <span className={cn("size-1.5 shrink-0 rounded-full", dotClass)} aria-hidden="true" />
          <span className="tabular-nums">{text}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        sideOffset={8}
        className="w-[330px] p-0"
        onMouseEnter={openNow}
        onMouseLeave={scheduleClose}
        // 键盘 Tab 从触发器进入内容区时，触发器 onBlur 会安排关闭；内容区获得焦点必须取消，
        // 否则 tooltip 内容刚被 Tab 聚焦就立刻关闭（键盘用户无法读取/点击「刷新」）。
        onFocus={openNow}
        onBlur={(event) => {
          if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
          scheduleClose();
        }}
        onOpenAutoFocus={(event) => event.preventDefault()}
      >
        <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
          <div className="text-xs font-medium">数据更新状态</div>
          <button
            type="button"
            onClick={() => void refreshNow()}
            className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label="立即刷新数据状态"
          >
            <RefreshCw className={cn("size-3", refreshing && "animate-spin")} aria-hidden="true" />
            刷新
          </button>
        </div>
        <ul className="max-h-[320px] divide-y divide-border/60 overflow-auto">
          {details.items.map((item) => {
            const itemTone = freshnessItemTone(item.status);
            return (
              <li key={item.dataset} className="flex items-start justify-between gap-2 px-3 py-2">
                <div className="min-w-0">
                  <div className="truncate text-[11px] font-medium">{item.label}</div>
                  <div className="mt-0.5 truncate text-[10px] text-muted-foreground">
                    {item.as_of ? item.as_of : "暂无数据"}
                    {item.lag_days != null && item.lag_days > 0 ? " · 落后 " + item.lag_days + " 天" : ""}
                    {item.updated_at ? " · 更新于 " + formatUpdatedAt(item.updated_at) : ""}
                  </div>
                  {item.note ? (
                    <div className="mt-0.5 text-[10px] leading-relaxed text-warning">{item.note}</div>
                  ) : null}
                </div>
                <span
                  className={cn(
                    "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium",
                    ITEM_TAG_TONE[itemTone],
                  )}
                >
                  {itemStatusText(item.status)}
                </span>
              </li>
            );
          })}
        </ul>
        <div className="border-t border-border px-3 py-2 text-[10px] leading-relaxed text-muted-foreground">
          {connectionStale ? (
            <p className="mb-1 text-warning">状态刷新失败，显示上次获取结果；正在自动重试…</p>
          ) : null}
          <p>{freshnessMetaSummary(freshness)}</p>
          <p className="mt-0.5">每 60 秒自动刷新 · 数据由各 ETL/估值任务落库后写入</p>
        </div>
      </PopoverContent>
    </Popover>
  );
}
