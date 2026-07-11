"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, CalendarDays } from "lucide-react";
import { api, type OtcCalendarDay } from "@/lib/api";
import { Button } from "./ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./ui/select";

const WEEK = ["一", "二", "三", "四", "五", "六", "日"];

function ymd(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function parseYmd(s?: string): Date | null {
  if (!s) return null;
  const d = new Date(s);
  return Number.isNaN(+d) ? null : d;
}

function monthRange(anchor: Date): { from: string; to: string; first: Date; days: number } {
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  const next = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1);
  const days = Math.round((+next - +first) / 86400000);
  return { from: ymd(first), to: ymd(new Date(+next - 86400000)), first, days };
}

const YEAR_MIN = 2019;
const YEAR_MAX = new Date().getFullYear() + 2;

/** 紧凑月历: 交易日 + 今日 + 期初/到期 pin + 存续期底色 */
export function MiniTradingCalendar({
  startDate,
  maturityDate,
  valuationDate,
  className = "",
}: {
  startDate?: string;
  maturityDate?: string;
  valuationDate?: string;
  className?: string;
}) {
  const [anchor, setAnchor] = useState(() => parseYmd(valuationDate) ?? new Date());
  const [map, setMap] = useState<Record<string, OtcCalendarDay>>({});
  const [loading, setLoading] = useState(false);
  const todayStr = ymd(new Date());

  const years = useMemo(() => {
    const ys: number[] = [];
    for (let y = YEAR_MIN; y <= YEAR_MAX; y++) ys.push(y);
    return ys;
  }, []);

  useEffect(() => {
    const vd = parseYmd(valuationDate);
    if (vd) setAnchor(new Date(vd.getFullYear(), vd.getMonth(), 1));
  }, [valuationDate]);

  const lifeRange = useMemo(() => {
    if (!startDate || !maturityDate) return null;
    const a = startDate <= maturityDate ? startDate : maturityDate;
    const b = startDate <= maturityDate ? maturityDate : startDate;
    return { lo: a, hi: b };
  }, [startDate, maturityDate]);

  useEffect(() => {
    const { from, to } = monthRange(anchor);
    let cancelled = false;
    setLoading(true);
    api
      .otcCalendar(from, to)
      .then((res) => {
        if (cancelled) return;
        const m: Record<string, OtcCalendarDay> = {};
        for (const d of res.days) m[d.date] = d;
        setMap(m);
      })
      .catch(() => !cancelled && setMap({}))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [anchor]);

  const { first, days } = monthRange(anchor);
  const leadBlanks = (first.getDay() + 6) % 7;
  const cells: (number | null)[] = [
    ...Array(leadBlanks).fill(null),
    ...Array.from({ length: days }, (_, i) => i + 1),
  ];

  const label = `${anchor.getFullYear()}年${anchor.getMonth() + 1}月`;

  return (
    <div className={`rounded-xl border border-border bg-card p-3 min-w-0 ${className}`}>
      <div className="flex items-center justify-between mb-2 gap-2">
        <div className="flex items-center gap-1.5 text-sm font-medium min-w-0">
          <CalendarDays className="w-4 h-4 text-primary shrink-0" />
          <span className="truncate">A股交易日历</span>
        </div>
        <div className="flex items-center gap-0.5 shrink-0">
          <Select
            value={String(anchor.getFullYear())}
            onValueChange={(v) => setAnchor(new Date(Number(v), anchor.getMonth(), 1))}
          >
            <SelectTrigger className="h-6 w-[5rem] text-xs px-1.5">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {years.map((y) => (
                <SelectItem key={y} value={String(y)} className="text-xs">
                  {y}年
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() - 1, 1))}>
            <ChevronLeft className="w-4 h-4" />
          </Button>
          <span className="text-xs text-muted-foreground w-14 text-center tabular-nums">{label.replace(/^\d+年/, "")}</span>
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1))}>
            <ChevronRight className="w-4 h-4" />
          </Button>
        </div>
      </div>
      <div className="grid grid-cols-7 gap-0.5 text-center">
        {WEEK.map((w) => (
          <div key={w} className="text-[10px] text-muted-foreground py-0.5">{w}</div>
        ))}
        {cells.map((day, i) => {
          if (day == null) return <div key={`b${i}`} />;
          const cellDate = new Date(anchor.getFullYear(), anchor.getMonth(), day);
          const ds = ymd(cellDate);
          const info = map[ds];
          const dow = cellDate.getDay();
          const isWeekend = dow === 0 || dow === 6;
          const trading = info?.is_trading ?? false;
          const isHoliday = !isWeekend && info != null && !trading;
          const isToday = ds === todayStr;
          const isStart = startDate === ds;
          const isMaturity = maturityDate === ds;
          const inLife = lifeRange && ds >= lifeRange.lo && ds <= lifeRange.hi && trading;
          let cls = "text-muted-foreground/40";
          if (isHoliday) cls = "text-amber-700 dark:text-amber-400 bg-amber-500/10";
          else if (trading) cls = "text-foreground";
          return (
            <div
              key={ds}
              title={
                (isHoliday ? "节假日" : trading ? "交易日" : isWeekend ? "周末" : "非交易日") +
                (isStart ? " · 初始观察日" : "") +
                (isMaturity ? " · 到期观察日" : "") +
                (inLife ? " · 存续期" : "")
              }
              className={`relative text-[11px] leading-6 rounded tabular-nums ${cls} ${
                isToday ? "ring-1 ring-primary" : ""
              } ${inLife && !isStart && !isMaturity ? "bg-primary/8" : trading && !isHoliday ? "hover:bg-muted/50" : ""} ${
                isStart ? "font-semibold text-emerald-600 dark:text-emerald-400" : ""
              } ${isMaturity ? "font-semibold text-orange-600 dark:text-orange-400" : ""}`}
            >
              {day}
              {isStart && (
                <span className="absolute -top-0.5 left-1/2 -translate-x-1/2 text-[8px] leading-none text-emerald-600 dark:text-emerald-400 font-bold">起</span>
              )}
              {isMaturity && (
                <span className="absolute -bottom-0.5 left-1/2 -translate-x-1/2 text-[8px] leading-none text-orange-600 dark:text-orange-400 font-bold">到</span>
              )}
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-foreground/70" />交易日</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-amber-500/25" />节假日</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-primary/25" />存续期</span>
        <span className="flex items-center gap-1"><span className="text-emerald-600 dark:text-emerald-400 font-bold">起</span>期初</span>
        <span className="flex items-center gap-1"><span className="text-orange-600 dark:text-orange-400 font-bold">到</span>到期</span>
        {loading && <span className="ml-auto">加载中…</span>}
      </div>
    </div>
  );
}
