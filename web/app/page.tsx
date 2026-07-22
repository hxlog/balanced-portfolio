import Link from "next/link";
import type { Metadata } from "next";
import { cacheLife } from "next/cache";
import { Button } from "@/components/ui/button";
import {
  ArrowRight,
  Activity,
  TrendingUp,
  Layers,
  CheckCircle2,
  Calculator,
} from "lucide-react";

export const metadata: Metadata = {
  title: "风险平价组合管理与回测平台",
  description:
    "基于桥水达利欧四象限框架的风险平价指数组合管理与回测工具：四象限选品、四种优化方法、无未来函数回测、绩效归因。",
  alternates: { canonical: "/" },
  openGraph: {
    title: "Balanced Portfolio | 风险平价组合管理与回测",
    description:
      "基于桥水达利欧四象限框架的风险平价指数组合管理与回测工具：四象限选品、四种优化方法、无未来函数回测、绩效归因。",
    url: "/",
    type: "website",
  },
};

export default async function Home() {
  "use cache";
  cacheLife("max");
  return (
    <div className="flex-1 flex flex-col">
      {/* Hero Section */}
      <section className="relative pt-32 pb-24 px-6 overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-primary/10 via-background to-background z-0 pointer-events-none"></div>
        <div className="container mx-auto max-w-5xl relative z-10 text-center">
          <div className="inline-flex items-center rounded-full border border-border px-3 py-1 text-sm text-muted-foreground mb-8">
            <span className="flex h-2 w-2 rounded-full bg-primary mr-2"></span>
            风险平价组合管理与回测工具
          </div>
          <h1 className="text-5xl md:text-7xl font-bold tracking-tight mb-6 leading-tight">
            {/* 强制换行 */}
            像机构一样 <br /> 配置全球大类资产
          </h1>
          <p className="text-xl text-muted-foreground max-w-3xl mx-auto mb-10 leading-relaxed">
            基于风险平价理论与桥水基金创始人Ray
            Dalio的四象限框架，给你一个可直接“抄作业”的指数投资方案。
            <br className="hidden md:block" />
            分散到刚刚好，长期夏普比率 &gt; 1，构建个性化的全天候策略。
          </p>
          <div className="flex flex-col sm:flex-row justify-center gap-4 flex-wrap">
            <Button asChild size="lg" className="rounded-full px-8 text-base">
              <Link href="/dashboard">
                风险平价回测系统 <ArrowRight className="ml-2 w-4 h-4" />
              </Link>
            </Button>
            <Button asChild size="lg" className="rounded-full px-8 text-base">
              <Link href="/cffex">
                股指期货数据看板 <ArrowRight className="ml-2 w-4 h-4" />
              </Link>
            </Button>
            <Button asChild size="lg" className="rounded-full px-8 text-base">
              <Link href="/otc-derivatives-pricing">
                场外衍生品定价 <ArrowRight className="ml-2 w-4 h-4" />
              </Link>
            </Button>
            <Button
              asChild
              size="lg"
              variant="outline"
              className="rounded-full px-8 text-base"
            >
              <a href="/methodology">了解方法论</a>
            </Button>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="py-24 px-6 bg-bg-subtle/50">
        <div className="container mx-auto max-w-6xl">
          <div className="grid md:grid-cols-3 gap-12">
            <div className="space-y-4">
              <div className="w-12 h-12 rounded-lg bg-primary/10 text-primary flex items-center justify-center">
                <Layers className="w-6 h-6" />
              </div>
              <h3 className="text-xl font-medium">分散到什么程度</h3>
              <p className="text-muted-foreground leading-relaxed">
                告别股债60/40经典组合，不再“均等分配”。我们通过历史相关性矩阵衡量各类资产风险，让每类投资组合对总波动率的贡献相等。
              </p>
            </div>
            <div className="space-y-4">
              <div className="w-12 h-12 rounded-lg bg-primary/10 text-primary flex items-center justify-center">
                <Activity className="w-6 h-6" />
              </div>
              <h3 className="text-xl font-medium">如何分散</h3>
              <p className="text-muted-foreground leading-relaxed">
                引入桥水基金CEO Ray
                Dalio的四象限框架，应对通胀/通缩与经济增长/收缩的四种宏观周期，确保在任何经济环境下都有资产表现优异。
              </p>
            </div>
            <div className="space-y-4">
              <div className="w-12 h-12 rounded-lg bg-primary/10 text-primary flex items-center justify-center">
                <TrendingUp className="w-6 h-6" />
              </div>
              <h3 className="text-xl font-medium">可回测、可复制</h3>
              <p className="text-muted-foreground leading-relaxed">
                全套方法论经过中国二级市场长期回测验证。每日提供最新权重，你可以清晰了解为何调仓、怎么调仓，知晓风险平价的价值。
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Methodology preview & Demo card */}
      <section id="methodology" className="py-32 px-6">
        <div className="container mx-auto max-w-6xl">
          <div className="grid lg:grid-cols-2 gap-16 items-center">
            <div className="space-y-8">
              <h2 className="text-3xl md:text-4xl font-semibold tracking-tight">
                四象限资产配置矩阵
              </h2>
              <p className="text-lg text-muted-foreground">
                经济环境在繁荣-萧条与通胀-通缩之间循环。我们将大类资产划分至四个象限，利用它们之间的低相关性和收益分布独立性构建全天候组合。
              </p>

              <div className="grid grid-cols-2 gap-px bg-border rounded-xl overflow-hidden shadow-sm">
                <div className="bg-card p-6 aspect-square flex flex-col justify-between">
                  <div className="text-sm font-medium text-up">
                    过热 (通胀↑ 增长↑)
                  </div>
                  <div className="text-sm text-muted-foreground">
                    国内宽基 / 商品
                  </div>
                </div>
                <div className="bg-card p-6 aspect-square flex flex-col justify-between">
                  <div className="text-sm font-medium text-weak">
                    滞胀 (通胀↑ 增长↓)
                  </div>
                  <div className="text-sm text-muted-foreground">
                    黄金 / 海外宽基
                  </div>
                </div>
                <div className="bg-card p-6 aspect-square flex flex-col justify-between">
                  <div className="text-sm font-medium text-primary">
                    复苏 (通胀↓ 增长↑)
                  </div>
                  <div className="text-sm text-muted-foreground">
                    红利 / 债券
                  </div>
                </div>
                <div className="bg-card p-6 aspect-square flex flex-col justify-between">
                  <div className="text-sm font-medium text-down">
                    衰退 (通胀↓ 增长↓)
                  </div>
                  <div className="text-sm text-muted-foreground">
                    债券 / 黄金
                  </div>
                </div>
              </div>
            </div>

            <div className="bg-card border border-border rounded-2xl p-8 shadow-sm">
              <div className="flex justify-between items-start mb-6">
                <div>
                  <h3 className="text-xl font-medium mb-1">
                    多资产投资组合中国市场调整版
                  </h3>
                  <p className="text-sm text-muted-foreground">
                    中证A500 · 标普500 · 黄金 · 10年国债...
                  </p>
                </div>
                <div className="px-3 py-1 bg-primary/10 text-primary rounded-full text-xs font-medium">
                  风险平价
                </div>
              </div>

              <div className="space-y-6">
                <div className="h-32 w-full bg-bg-subtle rounded-lg border border-border relative overflow-hidden flex items-end">
                  <svg
                    className="w-full h-full"
                    preserveAspectRatio="none"
                    viewBox="0 0 100 100"
                  >
                    <path
                      d="M0,100 L0,50 C20,60 30,30 50,40 C70,50 80,20 100,10 L100,100 Z"
                      fill="var(--primary)"
                      opacity="0.1"
                    />
                    <path
                      d="M0,50 C20,60 30,30 50,40 C70,50 80,20 100,10"
                      fill="none"
                      stroke="var(--primary)"
                      strokeWidth="2"
                      vectorEffect="non-scaling-stroke"
                    />
                  </svg>
                </div>

                <Button asChild className="w-full" variant="secondary">
                  <Link href="/dashboard">查看完整示例 &rarr;</Link>
                </Button>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* CFFEX Futures Dashboard */}
      <section className="py-24 px-6 bg-bg-subtle/50 border-t border-border">
        <div className="container mx-auto max-w-6xl">
          <div className="grid lg:grid-cols-2 gap-16 items-center">
            <div className="space-y-8">
              <h2 className="text-3xl md:text-4xl font-semibold tracking-tight">
                中金所股指期货看板
              </h2>
              <p className="text-lg text-muted-foreground">
                Alpha量化策略/期权交易对冲管理需要的股指期货看板，展示基差的时间序列与描述性统计，降低对冲成本。
              </p>

              <div className="space-y-5">
                <div className="flex items-start gap-4">
                  <div className="w-8 h-8 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0 mt-0.5">
                    <Activity className="w-4 h-4" />
                  </div>
                  <div>
                    <h4 className="text-base font-medium">合约监控</h4>
                    <p className="text-sm text-muted-foreground mt-1">
                      覆盖中金所股指期货品种的合约矩阵。
                    </p>
                  </div>
                </div>
                <div className="flex items-start gap-4">
                  <div className="w-8 h-8 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0 mt-0.5">
                    <TrendingUp className="w-4 h-4" />
                  </div>
                  <div>
                    <h4 className="text-base font-medium">升贴水率量化分析</h4>
                    <p className="text-sm text-muted-foreground mt-1">
                      使用合成综合年化升贴水率（0.6 × 次月 + 0.4 × 当季），剔除当月合约交割日异常基差波动。
                    </p>
                  </div>
                </div>
                <div className="flex items-start gap-4">
                  <div className="w-8 h-8 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0 mt-0.5">
                    <Layers className="w-4 h-4" />
                  </div>
                  <div>
                    <h4 className="text-base font-medium">描述性统计</h4>
                    <p className="text-sm text-muted-foreground mt-1">
                      统计标准差、分位值，当前值在历史分布中的位置一目了然。
                    </p>
                  </div>
                </div>
              </div>

              <div className="flex flex-col sm:flex-row gap-4 pt-4">
                <Button
                  asChild
                  size="lg"
                  className="rounded-full px-8 text-base"
                >
                  <Link href="/cffex">
                    进入看板 <ArrowRight className="ml-2 w-4 h-4" />
                  </Link>
                </Button>
                <Button
                  asChild
                  size="lg"
                  variant="outline"
                  className="rounded-full px-8 text-base"
                >
                  <Link href="/methodology#%E8%82%A1%E6%8C%87%E6%9C%9F%E8%B4%A7%E5%8D%87%E8%B4%B4%E6%B0%B4%E5%88%86%E6%9E%90">
                    了解升贴水率
                  </Link>
                </Button>
              </div>
            </div>

            <div className="bg-card border border-border rounded-2xl p-8 shadow-sm">
              <div className="flex justify-between items-start mb-6">
                <div>
                  <h3 className="text-xl font-medium mb-1">
                    沪深 300 股指期货
                  </h3>
                </div>
                <div className="px-3 py-1 bg-primary/10 text-primary rounded-full text-xs font-medium">
                  已收盘
                </div>
              </div>

              <div className="space-y-4 mb-8">
                {/* Mini contract table */}
                <div className="text-xs text-muted-foreground grid grid-cols-4 gap-2 border-b border-border pb-2">
                  <span>合约</span>
                  <span className="text-right">点位</span>
                  <span className="text-right">升贴水</span>
                  <span className="text-right">年化</span>
                </div>
                {[
                  {
                    sym: "IF2603",
                    type: "当月",
                    pt: "5,100.00",
                    pr: "+2.0%",
                    apr: "+8.5%",
                  },
                  {
                    sym: "IF2604",
                    type: "次月",
                    pt: "5,300.00",
                    pr: "+4.5%",
                    apr: "+12.3%",
                  },
                  {
                    sym: "IF2606",
                    type: "当季",
                    pt: "5,200.00",
                    pr: "+3.2%",
                    apr: "+6.1%",
                  },
                  {
                    sym: "IF2609",
                    type: "次季",
                    pt: "5,150.00",
                    pr: "+1.8%",
                    apr: "+2.9%",
                  },
                ].map((row) => (
                  <div
                    key={row.sym}
                    className="text-xs grid grid-cols-4 gap-2 py-1.5"
                  >
                    <span className="font-mono">
                      {row.sym}{" "}
                      <span className="text-[10px] text-muted-foreground">
                        {row.type}
                      </span>
                    </span>
                    <span className="text-right font-mono tabular-nums">
                      {row.pt}
                    </span>
                    <span
                      className={`text-right font-mono tabular-nums ${row.pr.startsWith("+") ? "text-up" : "text-down"}`}
                    >
                      {row.pr}
                    </span>
                    <span
                      className={`text-right font-mono tabular-nums font-medium ${row.apr.startsWith("+") ? "text-up" : "text-down"}`}
                    >
                      {row.apr}
                    </span>
                  </div>
                ))}
              </div>

              {/* <Button asChild className="w-full" variant="secondary">
                <Link href="/cffex">打开看板 &rarr;</Link>
              </Button> */}
            </div>
          </div>
        </div>
      </section>

      {/* OTC Derivatives Pricing */}
      <section className="py-24 px-6 border-t border-border">
        <div className="container mx-auto max-w-6xl">
          <div className="grid lg:grid-cols-2 gap-16 items-center">
            <div className="space-y-8">
              <h2 className="text-3xl md:text-4xl font-semibold tracking-tight">
                场外结构化衍生品定价
              </h2>
              <p className="text-lg text-muted-foreground">
                <b>一站式场外期权的盈亏与敞口分析</b>
                <br />
                支持雪球、凤凰、气囊、障碍等结构的定价与簿记。
                <br />
                求解方法：Monte Carlo / Black-Scholes Model 闭式解解析 / 数值积分法。
                <br />
                按A股交易日历展示合约的Greeks、PV值、PoL与收益示意图。

                
              </p>

              <div className="space-y-5">
                <div className="flex items-start gap-4">
                  <div className="w-8 h-8 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0 mt-0.5">
                    <Calculator className="w-4 h-4" />
                  </div>
                  <div>
                    <h4 className="text-base font-medium">多品种结构</h4>
                    <p className="text-sm text-muted-foreground mt-1">
                      雪球双票息（敲出 / 红利）、凤凰派息、气囊参与率、障碍敲入敲出。
                    </p>
                  </div>
                </div>
                <div className="flex items-start gap-4">
                  <div className="w-8 h-8 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0 mt-0.5">
                    <Activity className="w-4 h-4" />
                  </div>
                  <div>
                    <h4 className="text-base font-medium">交易日历蒙特卡洛</h4>
                    <p className="text-sm text-muted-foreground mt-1">
                      敲入按交易日路径观测，敲出仅在月度观察日判定；票息 ACT/365 计息、
                      Bus/252 折现，路径步长与日历一致。
                    </p>
                  </div>
                </div>
                <div className="flex items-start gap-4">
                  <div className="w-8 h-8 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0 mt-0.5">
                    <TrendingUp className="w-4 h-4" />
                  </div>
                  <div>
                    <h4 className="text-base font-medium">簿记与 Greeks</h4>
                    <p className="text-sm text-muted-foreground mt-1">
                      登录后可保存条款、重估与排序；Bump-and-reprice 输出 Delta/Gamma/Vega 等，
                      示意图标注敲入敲出线与累计盈亏。
                    </p>
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap gap-3">
                <Button asChild>
                  <Link href="/otc-derivatives-pricing">
                    打开定价页 <ArrowRight className="ml-2 w-4 h-4" />
                  </Link>
                </Button>
                <Button asChild variant="outline">
                  <Link href="/methodology#%E5%9C%BA%E5%A4%96%E7%BB%93%E6%9E%84%E5%8C%96%E4%BA%A7%E5%93%81%E5%AE%9A%E4%BB%B7">
                    查看方法论
                  </Link>
                </Button>
              </div>
            </div>

            <div className="rounded-xl border border-border bg-card p-6 space-y-4 shadow-sm">
              <div className="flex items-center justify-between">
                <h3 className="font-medium">支持结构一览</h3>
                <span className="text-xs text-muted-foreground">MC / 解析</span>
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                {[
                  { name: "雪球", desc: "敲出票息 + 红利票息" },
                  { name: "凤凰", desc: "条件派息 + 敲入敲出" },
                  { name: "气囊", desc: "下行保护 + 参与率" },
                  { name: "障碍", desc: "敲入/敲出香草变体" },
                ].map((row) => (
                  <div
                    key={row.name}
                    className="rounded-lg border border-border/60 bg-bg-subtle/40 px-3 py-3"
                  >
                    <div className="font-medium">{row.name}</div>
                    <div className="text-xs text-muted-foreground mt-1">{row.desc}</div>
                  </div>
                ))}
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed">
                挂钩可选指数标的，自动读取初始观察日点位与近窗历史波动率建议值；
                匿名可浏览示例簿记结果，登录后可自建簿记。
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Target Audience */}
      <section className="py-24 px-6 border-t border-border">
        <div className="container mx-auto max-w-4xl text-center">
          <h2 className="text-2xl font-medium mb-12">为专业投资者设计</h2>
          <div className="flex flex-col sm:flex-row justify-center gap-12 text-muted-foreground">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="text-primary w-5 h-5" />
              <span>机构投资者</span>
            </div>
            <div className="flex items-center gap-3">
              <CheckCircle2 className="text-primary w-5 h-5" />
              <span>专业投资者</span>
            </div>
            <div className="flex items-center gap-3">
              <CheckCircle2 className="text-primary w-5 h-5" />
              <span>资深二级市场散户</span>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
