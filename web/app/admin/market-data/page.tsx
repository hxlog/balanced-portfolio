import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { DataHealthPanel } from "@/components/admin/DataHealthPanel";

export const metadata: Metadata = {
  title: "数据健康 · 管理后台",
  description: "行情 ETL 就绪状态、源可用性、质量问题与追赶队列。",
  robots: { index: false, follow: false },
};

export default function AdminDataHealthPage() {
  return (
    <main className="mx-auto w-full max-w-[1600px] px-5 py-6">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Link href="/admin/assets" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" /> 返回资产管理
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">数据健康</h1>
      </div>
      <p className="mb-4 text-sm text-muted-foreground">
        四大数据集（A 股 / 港股 / 场内基金 / 场外基金）的当日就绪、无限追赶队列、源可用性与质量问题。
        仅超级管理员可见；页面只读展示，重放操作会写审计日志并触发一次补拉波次。
      </p>
      <DataHealthPanel />
    </main>
  );
}
