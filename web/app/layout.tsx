import type { Metadata } from "next";
import { Suspense } from "react";
import "./globals.css";
import "katex/dist/katex.min.css";
import { Providers } from "./providers";
import { AuthProvider } from "@/lib/auth";
import { Navbar } from "@/components/Navbar";

const SITE_URL = process.env.BP_SITE_URL || "http://localhost:3000";
const SITE_NAME = "Balanced Portfolio";
const SITE_DESC =
  "面向机构与专业投资者的风险平价指数投资组合管理与回测平台，基于桥水达利欧四象限框架。";

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
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="min-h-screen flex flex-col bg-background text-foreground font-sans antialiased">
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
        <Providers>
          <Suspense fallback={null}>
            <AuthProvider>
              <Navbar />
              <main className="flex-1 flex flex-col min-w-0">{children}</main>
            </AuthProvider>
          </Suspense>
          <footer className="border-t border-border py-8 text-center text-sm text-muted-foreground mt-auto">
            <div className="container mx-auto max-w-7xl px-4 sm:px-6 flex flex-col items-center gap-3">
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
              <span>© 2026 Balanced Portfolio contributors</span>
            </div>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
