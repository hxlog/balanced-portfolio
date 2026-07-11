"use client";

import * as echarts from "echarts";
import { useEffect, useRef } from "react";
import type { CSSProperties } from "react";

// 直接驱动 echarts 核心: useEffect(commit 后) 内 init/setOption/resize/dispose,
// 避开 echarts-for-react 在 React19 StrictMode 下 "setOption during main process" 告警。
export function EChart({
  option,
  style,
}: {
  option: Record<string, unknown>;
  style?: CSSProperties;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  // 初始化 + 卸载
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chartRef.current = chart;

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);

    return () => {
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  // option 变化时更新
  useEffect(() => {
    if (chartRef.current) {
      chartRef.current.setOption(option, { notMerge: false, lazyUpdate: true });
    }
  }, [option]);

  return <div ref={ref} style={style || { height: 300, width: "100%" }} />;
}
