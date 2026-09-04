"use client";

import { useState } from "react";
import { Maximize2, X } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import { EChart } from "@/components/EChart";
import { getChartTheme } from "@/lib/chart-theme";

/**
 * 图表放大灯箱: 点击「放大」将绑定图表以近乎全屏的浮层展示(类似图片灯箱),
 * 用于多资产可视化(相关/协方差矩阵、象限矩阵、持仓占比等)在宽幅场景下也能看清。
 * 灯箱内图表用 ResizeObserver 自适应, 高度随内容放大; 内容超高时可纵向滚动。
 * 主题自适应: 白天白色/浅灰底色, 暗黑模式深色(与 Dashboard 的 cardBg 口径一致)。
 */
export function ChartLightbox({
  title,
  description,
  option,
  label,
  className,
  disabled,
}: {
  title: string;
  description?: string;
  option: Record<string, unknown>;
  label?: string;
  className?: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const theme = getChartTheme(isDark);

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className={className}
        onClick={() => setOpen(true)}
        disabled={disabled}
        title={`放大查看${label ? `：${label}` : ""}`}
        aria-label={`放大查看${label ? `：${label}` : ""}`}
      >
        <Maximize2 className="w-4 h-4" />
      </Button>

      {open && (
        <div
          className={`fixed inset-0 z-[100] flex flex-col ${
            isDark
              ? "bg-black/70 backdrop-blur-sm"
              : "bg-slate-400/40 backdrop-blur-sm"
          }`}
          role="dialog"
          aria-modal="true"
          aria-label={title}
          onClick={(e) => {
            if (e.target === e.currentTarget) setOpen(false);
          }}
        >
          <div
            className={`flex items-center justify-between gap-3 px-5 py-3 shrink-0 border-b ${
              isDark ? "border-white/10" : "border-slate-300/60"
            }`}
          >
            <div className="min-w-0">
              <h2 className="text-sm font-medium truncate" style={{ color: theme.text }}>
                {title}
              </h2>
              {description && (
                <p
                  className={`text-xs mt-0.5 leading-relaxed ${
                    isDark ? "text-white/60" : "text-slate-500"
                  }`}
                >
                  {description}
                </p>
              )}
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className={`shrink-0 ${
                isDark
                  ? "text-white/80 hover:text-white hover:bg-white/10"
                  : "text-slate-600 hover:text-slate-900 hover:bg-slate-200/60"
              }`}
              onClick={() => setOpen(false)}
              aria-label="关闭放大视图"
            >
              <X className="w-5 h-5" />
            </Button>
          </div>
          <div className="flex-1 min-h-0 overflow-auto p-4 sm:p-6">
            <div
              className="rounded-xl p-4 min-w-[720px]"
              style={{ backgroundColor: theme.tooltipBg }}
            >
              <EChart
                option={option}
                style={{ height: "calc(100vh - 140px)", minHeight: 640, width: "100%" }}
              />
            </div>
          </div>
        </div>
      )}
    </>
  );
}