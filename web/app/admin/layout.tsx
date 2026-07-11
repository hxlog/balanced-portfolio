import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "管理后台",
  description: "Balanced Portfolio 管理后台（不公开索引）。",
  robots: { index: false, follow: false },
};

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <div className="flex-1 flex flex-col min-w-0 w-full">{children}</div>;
}
