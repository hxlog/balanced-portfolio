import { Suspense } from "react";
import type { Metadata } from "next";
import { OtcPricingClient } from "./OtcPricingClient";
import OtcDerivativesPricingLoading from "./loading";

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
  // 路由骨架与真实布局同尺寸：客户端 hydration / 数据到达时替换不产生 layout shift。
  return (
    <Suspense fallback={<OtcDerivativesPricingLoading />}>
      <OtcPricingClient />
    </Suspense>
  );
}
