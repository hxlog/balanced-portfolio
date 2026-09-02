"use client";

import * as echarts from "echarts";
import { useLayoutEffect, useRef } from "react";
import type { CSSProperties } from "react";

// 直接驱动 echarts 核心: useLayoutEffect(commit 后、paint 前同步) 内 init/setOption/resize/dispose,
// 避开 echarts-for-react 在 React19 StrictMode 下 "setOption during main process" 告警,
// 也保证在容器(尤其条件渲染的全屏灯箱 calc 高度)布局完成后才 init, 避免 canvas 拿到 0 尺寸渲染空白。
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
  useLayoutEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chartRef.current = chart;

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    // 兜底: 容器尺寸在挂载瞬间尚未就绪(如 flex/calc 高度)时, 主动 resize 一次强制刷新 canvas 尺寸。
    chart.resize();

    return () => {
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  // option 变化时更新
  useLayoutEffect(() => {
    if (chartRef.current) {
      chartRef.current.setOption(option, { notMerge: false, lazyUpdate: true });
    }
  }, [option]);

  return <div ref={ref} style={style || { height: 300, width: "100%" }} />;
}
