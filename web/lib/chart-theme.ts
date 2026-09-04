/** 全站 ECharts 主题: 明暗两套, 收敛各页面硬编码。 */
export interface ChartTheme {
  text: string; subtext: string;
  axisLine: string; splitLine: string;
  tooltipBg: string; tooltipBorder: string;
  up: string; down: string;
  palette: string[];
  cffex: { IF: string; IH: string; IC: string; IM: string };
  crypto: { btc: string; sp500: string; nasdaq: string; gold: string; dxy: string };
  rdBu: string[]; // 相关性热力图发散色(蓝-白-红)
  // OTC 路径示意图的语义色 (与涨跌状态色解耦: 敲入=危险红, 敲出/结构色=成功绿, 盈亏=琥珀)
  otc: {
    ki: string; ko: string; pnl: string;
    expire: string; neutral: string;
    obsDotted: string; // 月度观察日虚线
    lockFill: string; // 锁定期 markArea 填充
  };
  // 各色系的半透明面积填充 (ECharts areaStyle 用)
  fills: {
    primary05: string; primarySoft: string; primaryFaint: string;
    btcSoft: string; dxySoft: string;
  };
}

const light: ChartTheme = {
  text: "#171717", subtext: "#666666",
  axisLine: "rgba(0,0,0,0.15)", splitLine: "rgba(0,0,0,0.06)",
  tooltipBg: "#FFFFFF", tooltipBorder: "rgba(0,0,0,0.10)",
  up: "#16A34A", down: "#DC2626",
  palette: ["#0284C7", "#16A34A", "#D97706", "#DC2626", "#7C3AED", "#0891B2", "#DB2777", "#65A30D"],
  cffex: { IF: "#0284C7", IH: "#D97706", IC: "#DC2626", IM: "#16A34A" },
  crypto: { btc: "#D97706", sp500: "#0284C7", nasdaq: "#7C3AED", gold: "#B45309", dxy: "#0891B2" },
  rdBu: ["#2166AC", "#4393C3", "#92C5DE", "#D1E5F0", "#F7F7F7", "#FDDBC7", "#F4A582", "#D6604D", "#B2182B"],
  otc: {
    ki: "#ef4444", ko: "#10b981", pnl: "#f59e0b",
    expire: "#94a3b8", neutral: "#94a3b8",
    obsDotted: "rgba(148,163,184,0.55)",
    lockFill: "rgba(234,179,8,0.14)",
  },
  fills: {
    primary05: "rgba(2,132,199,0.05)", primarySoft: "rgba(2,132,199,0.3)", primaryFaint: "rgba(2,132,199,0.12)",
    btcSoft: "rgba(217,119,6,0.12)", dxySoft: "rgba(217,119,6,0.12)",
  },
};

const dark: ChartTheme = {
  text: "#EDEDED", subtext: "#A1A1A1",
  axisLine: "rgba(255,255,255,0.15)", splitLine: "rgba(255,255,255,0.08)",
  tooltipBg: "#1C1C1E", tooltipBorder: "rgba(255,255,255,0.12)",
  up: "#4ADE80", down: "#F87171",
  palette: ["#38BDF8", "#4ADE80", "#FBBF24", "#F87171", "#A78BFA", "#22D3EE", "#F472B6", "#A3E635"],
  cffex: { IF: "#38BDF8", IH: "#FBBF24", IC: "#F87171", IM: "#4ADE80" },
  crypto: { btc: "#FBBF24", sp500: "#38BDF8", nasdaq: "#A78BFA", gold: "#F59E0B", dxy: "#22D3EE" },
  rdBu: ["#2166AC", "#4393C3", "#92C5DE", "#D1E5F0", "#2A2A2A", "#FDDBC7", "#F4A582", "#D6604D", "#B2182B"],
  otc: {
    ki: "#f87171", ko: "#34d399", pnl: "#fbbf24",
    expire: "#94a3b8", neutral: "#94a3b8",
    obsDotted: "rgba(148,163,184,0.45)",
    lockFill: "rgba(234,179,8,0.12)",
  },
  fills: {
    primary05: "rgba(56,189,248,0.05)", primarySoft: "rgba(56,189,248,0.3)", primaryFaint: "rgba(56,189,248,0.15)",
    btcSoft: "rgba(251,191,36,0.15)", dxySoft: "rgba(251,191,36,0.15)",
  },
};

export function getChartTheme(isDark: boolean): ChartTheme {
  return isDark ? dark : light;
}

/** 把 6 位 hex 转为 rgba()，用于面积渐变等透明度派生（保持与主题色同源）。 */
export function withAlpha(hex: string, alpha: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}
