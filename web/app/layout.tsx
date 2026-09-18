import type { Metadata } from "next";
import { Suspense } from "react";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import "katex/dist/katex.min.css";
import { Providers } from "./providers";
import { AuthProvider } from "@/lib/auth";
import { Navbar } from "@/components/Navbar";
import { BackToTop } from "@/components/BackToTop";
import { Toaster } from "@/components/ui/sonner";

// Geist 西文栈(Next.js 官网同款): 中文自动回落 PingFang SC / Microsoft YaHei(见 globals.css --font-sans)
const geistSans = Geist({ subsets: ["latin"], variable: "--font-geist-sans", display: "swap" });
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono", display: "swap" });

const SITE_URL = process.env.BP_SITE_URL || "http://localhost:3000";
const SITE_NAME = "Balanced Portfolio";
const SITE_DESC =
  "面向机构与专业投资者的风险平价指数投资组合管理与回测平台，基于桥水达利欧四象限框架。";

// umami 站点埋点: 仅生产环境且配置了 website-id 时启用(开发环境不调用)。
//
// 两个独立 bundle: script.js 是访客统计(必需)；recorder.js 是会话回放+热力图(可选)。
// 回放**不是** script.js 的一个属性 —— 必须单独注入 recorder.js, 否则 umami 后台
// 的 Replays 永远为空(实测 v3.3.1: script.js 内 'recorder'/'rrweb' 零命中)。
// recorder.js 通过 window.umami.getSession() 拿会话缓存, 依赖 script.js 先执行;
// 两个都用原生 <script defer>, 外部脚本按文档顺序执行, 故顺序天然正确。
// (勿改用 next/script: commit 1de8072 曾因此产生 hydration 问题而回退到原生 defer。)
const UMAMI_WEBSITE_ID = process.env.BP_UMAMI_WEBSITE_ID || "";
const UMAMI_SRC = process.env.BP_UMAMI_SRC || "https://umami.morean.cn/script.js";
const UMAMI_RECORDER_SRC =
  process.env.BP_UMAMI_RECORDER_SRC ||
  UMAMI_SRC.replace(/\/script\.js$/, "/recorder.js");
const IS_PROD = process.env.NODE_ENV === "production";
const ENABLE_UMAMI = IS_PROD && UMAMI_WEBSITE_ID.length > 0;
// 回放/热力图开关: 单独可控, 便于在不需要录屏时省掉 190KB 的 recorder bundle。
const ENABLE_UMAMI_REPLAY = ENABLE_UMAMI && UMAMI_RECORDER_SRC.length > 0
  && UMAMI_RECORDER_SRC !== UMAMI_SRC;

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: `${SITE_NAME} | 风险平价组合管理与回测`,
    template: `%s | ${SITE_NAME}`,
  },
  description: SITE_DESC,
  applicationName: SITE_NAME,
  keywords: [
    "风险平价", "全天候组合", "达利欧四象限", "桥水", "投资组合", "回测", "Risk Parity", "ERC",
    "资产配置", "量化", "Dalio", "All Weather",
  ],
  authors: [{ name: "Balanced Portfolio" }],
  creator: "Balanced Portfolio",
  publisher: "Balanced Portfolio",
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    locale: "zh_CN",
    url: SITE_URL,
    siteName: SITE_NAME,
    title: `${SITE_NAME} | 风险平价组合管理与回测`,
    description: SITE_DESC,
    images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: SITE_NAME }],
  },
  twitter: {
    card: "summary_large_image",
    title: `${SITE_NAME} | 风险平价组合管理与回测`,
    description: SITE_DESC,
    images: ["/opengraph-image"],
  },
  robots: {
    index: true,
    follow: true,
    googleBot: { index: true, follow: true, "max-image-preview": "large" },
  },
  icons: { icon: "/icon", apple: "/icon" },
  category: "finance",
};

const jsonLd = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      name: SITE_NAME,
      url: SITE_URL,
      description: SITE_DESC,
    },
    {
      "@type": "WebSite",
      name: SITE_NAME,
      url: SITE_URL,
      inLanguage: "zh-CN",
      description: SITE_DESC,
    },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className={`${geistSans.variable} ${geistMono.variable}`} suppressHydrationWarning>
      <body className="min-h-screen flex flex-col bg-background text-foreground font-sans antialiased selection:bg-cyan-100 dark:selection:bg-zinc-800">
        {ENABLE_UMAMI && (
          <script key="umami" defer src={UMAMI_SRC} data-website-id={UMAMI_WEBSITE_ID} />
        )}
        {ENABLE_UMAMI_REPLAY && (
          <script
            key="umami-recorder"
            defer
            src={UMAMI_RECORDER_SRC}
            data-website-id={UMAMI_WEBSITE_ID}
          />
        )}
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
        <Providers>
          <Suspense fallback={null}>
            <AuthProvider>
              <Navbar />
              <main className="flex-1 flex flex-col min-w-0">{children}</main>
              <BackToTop />
              <Toaster />
            </AuthProvider>
          </Suspense>
          <footer className="border-t border-border py-8 text-center text-sm text-muted-foreground mt-auto">
            <div className="container mx-auto max-w-[1440px] md:px-4 sm:px-6 flex flex-col items-center gap-3">
              <p className="leading-relaxed max-w-2xl">
                Balanced Portfolio 是开源的风险平价组合管理与回测项目。本工具仅供研究，不构成投资建议。
              </p>
              <a
                href="https://github.com/hxlog/balanced-portfolio"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-foreground transition-colors"
                aria-label="在 GitHub 查看 Balanced Portfolio 源代码"
              >
                GitHub 源代码
              </a>
              <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-xs">
                <span>© 2026 Balanced Portfolio</span>
                <span aria-hidden="true" className="text-border">
                  |
                </span>
                <a
                  href="https://beian.miit.gov.cn/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:text-foreground transition-colors"
                >
                  粤ICP备2024174552号-2
                </a>
              </div>
            </div>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
