import { NextRequest, NextResponse } from "next/server";
import { revalidateTag } from "next/cache";
import { apiBase, readSessionToken } from "@/lib/session-server";

/**
 * 失效 /builder 的 SSR 资产缓存(默认 tag=assets)。
 *
 * 仅超级管理员可调用: admin 资产管理在 保存/删除/启停 后触发, 让 /builder 下次访问
 * 立即看到变化, 不必等 cacheLife("hours") TTL、不必重启。
 * 路由由 Next Route Handler 处理(rewrites afterFiles 语义下文件系统路由优先,
 * 不会被 /api/:path* rewrite 转给 FastAPI)。
 */
export async function POST(request: NextRequest) {
  const token = await readSessionToken();
  if (!token) {
    return NextResponse.json({ detail: "未登录" }, { status: 401 });
  }
  // 复用 FastAPI 鉴权链: 校验 token 有效且为 super_admin(role === "admin")
  const res = await fetch(`${apiBase()}/api/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    return NextResponse.json({ detail: "鉴权失败" }, { status: 401 });
  }
  const profile = await res.json().catch(() => ({} as { role?: string }));
  if (profile.role !== "admin") {
    return NextResponse.json({ detail: "需要超级管理员权限" }, { status: 403 });
  }
  // body 可选 { tag?: string }, 缺省失效 assets
  let tag = "assets";
  try {
    const body = await request.json();
    if (body && typeof body.tag === "string" && body.tag) tag = body.tag;
  } catch {
    /* 无 body 或非 JSON, 走默认 tag */
  }
  // profile 必须与 web/lib/cached-data.ts 的 cacheLife("hours") 一致, 否则失效不到该缓存
  revalidateTag(tag, "hours");
  return NextResponse.json({ ok: true, tag });
}
