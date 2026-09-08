import Link from "next/link";
import { connection } from "next/server";
import { ArrowRight } from "lucide-react";
import { getCachedCryptoCorrelation } from "@/lib/cached-data";
import type { CryptoCorrelationResponse } from "@/lib/api";
import {
  AMBER_BADGE_CLASS,
  CRYPTO_PAIR_ORDER,
  type CryptoPriceField,
  fmtAssetPrice,
  fmtCorr,
  fmtCryptoAsOf,
  lastCorr,
} from "@/lib/crypto-format";

// ---------------------------------------------------------------------------
// Sparkline: server-rendered inline SVG (不用 EChart — 扁平 + 轻量, 参考
// web/app/page.tsx 的 inline SVG 口径)。4 条 3M-Pearson 叠线, headline=comex_gold
// (var(--primary), 1.5px), 其余 var(--muted-foreground) 1px 低透明。null 缺口
// (滚动热身 / ffill 断点) 用分段 M 处理。CSS 变量暗色自洽 (server component 不能 useTheme)。
// ---------------------------------------------------------------------------

function Sparkline({ data }: { data: CryptoCorrelationResponse }) {
  const W = 100;
  const H = 44;
  const pearson = data.rolling?.["3M"]?.pearson;
  const dates = data.dates ?? [];
  if (!pearson || !dates.length) {
    return <div className="h-11 w-full rounded-md bg-bg-subtle/60" />;
  }
  const n = dates.length;
  const segs: Record<string, string[]> = {};
  for (const { key } of CRYPTO_PAIR_ORDER) {
    const arr = pearson[key]?.correlation ?? [];
    const d: string[] = [];
    let pen = false;
    for (let i = 0; i < n; i++) {
      const v = arr[i];
      if (v == null || Number.isNaN(v)) {
        pen = false;
        continue;
      }
      const x = n === 1 ? 0 : (i / (n - 1)) * W; // 0..100
      const y = ((1 - v) / 2) * H; // corr +1→0(top), -1→H(bot), 0→H/2
      d.push(`${pen ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`);
      pen = true;
    }
    segs[key] = d;
  }
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className="w-full h-11"
      role="img"
      aria-label="BTC 3 个月滚动相关性"
    >
      <line
        x1="0"
        y1={H / 2}
        x2={W}
        y2={H / 2}
        stroke="var(--border)"
        strokeWidth="1"
        vectorEffect="non-scaling-stroke"
      />
      {CRYPTO_PAIR_ORDER.map(({ key, headline }) => {
        const d = segs[key];
        if (!d.length) return null;
        return (
          <path
            key={key}
            d={d.join(" ")}
            fill="none"
            stroke={headline ? "var(--primary)" : "var(--muted-foreground)"}
            strokeWidth={headline ? 1.5 : 1}
            strokeOpacity={headline ? 0.9 : 0.45}
            strokeLinejoin="round"
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
          />
        );
      })}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// HomeCryptoSection (async server component, PPR 动态洞)
// connection() 退静态预渲染 (build/CI 时 FastAPI 未运行); getCachedCryptoCorrelation
// 的 "use cache" 仍缓存数据 (cacheTag "crypto")。失败 throw → catch → null
// (不缓存 null, 无 stale null), 渲染极简 fallback 不阻断首页。
// ---------------------------------------------------------------------------

export async function HomeCryptoSection() {
  await connection();
  let data: CryptoCorrelationResponse | null = null;
  try {
    data = await getCachedCryptoCorrelation();
  } catch (e) {
    console.error("home crypto SSR fetch failed:", e);
  }

  if (!data) {
    return (
      <section className="py-24 px-6 border-t border-border">
        <div className="container mx-auto max-w-[1440px]">
          <div className="border border-border rounded-xl bg-card p-8 flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-semibold tracking-tight">
                加密货币看板
              </h2>
              <p className="text-sm text-muted-foreground mt-1">数据加载中…</p>
            </div>
            <Link
              href="/crypto"
              className="text-sm text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
            >
              查看完整看板 <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        </div>
      </section>
    );
  }

  const snap = data.snapshot;
  const meta = data.meta;
  const asOf = fmtCryptoAsOf(meta);
  const pearson = data.rolling?.["3M"]?.pearson;

  const assets: { key: string; label: string; field: CryptoPriceField }[] = [
    { key: "btc", label: "BTC/USD", field: "btc" },
    { key: "dxy", label: "DXY", field: "dxy" },
    { key: "comex_gold", label: "COMEX金", field: "comex_gold" },
    { key: "au0_gold", label: "沪金AU0", field: "au0_gold" },
    { key: "sp500", label: "标普500", field: "sp500" },
    { key: "nasdaq", label: "纳斯达克", field: "nasdaq" },
  ];

  return (
    <section className="py-24 px-6 border-t border-border">
      <div className="container mx-auto max-w-[1440px]">
        <div className="border border-border rounded-xl bg-card p-8">
          {/* Header */}
          <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-8">
            <div>
              <h2 className="text-2xl font-semibold tracking-tight">加密货币看板</h2>
              <p className="text-sm text-muted-foreground mt-1">比特币相关性分析</p>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              {asOf.et && asOf.cn && (
                <span className="inline-flex items-center rounded-full border border-border px-2.5 py-0.5 text-xs text-muted-foreground">
                  数据截至 {asOf.et} / {asOf.cn}
                </span>
              )}
              {meta?.is_synced === false && meta?.effective_td && (
                <span
                  className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs ${AMBER_BADGE_CLASS}`}
                >
                  数据待齐 · 展示至 {meta.effective_td}
                </span>
              )}
            </div>
          </div>

          {/* 6-asset price row */}
          <div className="grid grid-cols-3 md:grid-cols-6 gap-x-6 gap-y-4">
            {assets.map((a) => (
              <div key={a.key}>
                <div className="text-xs text-muted-foreground mb-1">{a.label}</div>
                <div className="text-lg font-mono tabular-nums">
                  {fmtAssetPrice(a.field, snap[a.field] ?? null)}
                </div>
              </div>
            ))}
          </div>

          <div className="border-t border-border my-6" />

          {/* 4-correlation row (3M Pearson, latest) */}
          <div className="mb-4">
            <h3 className="text-sm font-medium">3 个月 Pearson R</h3>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-4">
            {CRYPTO_PAIR_ORDER.map(({ key, label, headline }) => (
              <div key={key}>
                <div className="text-xs text-muted-foreground mb-1">vs {label}</div>
                <div
                  className={`text-lg font-mono tabular-nums ${
                    headline ? "text-primary" : "text-foreground"
                  }`}
                >
                  {fmtCorr(lastCorr(pearson?.[key]?.correlation))}
                </div>
              </div>
            ))}
          </div>

          <div className="border-t border-border my-6" />

          {/* Sparkline + CTA */}
          <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
            <div className="flex-1 min-w-0">
              <div className="text-xs text-muted-foreground mb-2">
                BTC 3M 滚动相关性
              </div>
              <Sparkline data={data} />
            </div>
            <Link
              href="/crypto"
              className="text-sm text-muted-foreground hover:text-foreground inline-flex items-center gap-1 shrink-0"
            >
              查看完整看板 <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
