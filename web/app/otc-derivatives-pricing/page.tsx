import { Suspense } from "react";
import type { Metadata } from "next";
import { OtcPricingClient } from "./OtcPricingClient";

export const metadata: Metadata = {
  title: "场外衍生品定价 — 雪球/凤凰/气囊/障碍",
  description:
    "场外结构化产品定价与簿记：雪球、凤凰、气囊、障碍结构；蒙特卡洛/解析定价 + 全套 Greeks，A股交易日历、挂钩指数历史波动率与收益-波动示意图。",
  alternates: { canonical: "/otc-derivatives-pricing" },
  openGraph: {
    title: "场外衍生品定价 | Balanced Portfolio",
    description:
      "雪球/凤凰/气囊/障碍 场外结构化产品定价、Greeks、簿记与收益-波动示意图，参考 pricelib 品种与算法。",
    url: "/otc-derivatives-pricing",
  },
};

export default function OtcDerivativesPricingPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-background flex items-center justify-center">
          <div className="text-muted-foreground text-sm">加载中...</div>
        </div>
      }
    >
      <OtcPricingClient />
    </Suspense>
  );
}
