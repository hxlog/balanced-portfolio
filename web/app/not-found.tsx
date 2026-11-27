import Link from "next/link";
import type { Metadata } from "next";
import { Compass } from "lucide-react";

import { Button } from "@/components/ui/button";

export const metadata: Metadata = {
  title: "页面不存在",
  robots: { index: false, follow: false },
};

const QUICK_LINKS = [
  { href: "/", label: "返回首页" },
  { href: "/dashboard", label: "风险平价回测" },
  { href: "/valuation", label: "指数估值" },
  { href: "/methodology", label: "方法论" },
];

export default function NotFound() {
  return (
    <div className="flex flex-1 items-center justify-center px-6 py-24">
      <div className="w-full max-w-md space-y-4 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
          <Compass className="h-6 w-6" aria-hidden="true" />
        </div>
        <p className="font-mono text-sm text-muted-foreground tabular-nums">404</p>
        <h1 className="text-2xl font-semibold tracking-tight">页面不存在</h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          你访问的页面可能已被移动或删除。可以从下面的入口重新开始。
        </p>
        <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
          {QUICK_LINKS.map((item) => (
            <Button key={item.href} asChild variant={item.href === "/" ? "default" : "outline"} size="sm">
              <Link href={item.href}>{item.label}</Link>
            </Button>
          ))}
        </div>
      </div>
    </div>
  );
}
