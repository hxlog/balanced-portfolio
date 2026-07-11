import { NextRequest, NextResponse } from "next/server";
import { apiBase, readSessionToken, setSessionToken } from "@/lib/session-server";

export async function POST(request: NextRequest) {
  let token = await readSessionToken();
  if (!token) {
    const auth = request.headers.get("authorization") || "";
    if (auth.toLowerCase().startsWith("bearer ")) {
      token = auth.slice(7).trim();
    }
  }
  if (!token) {
    return NextResponse.json({ detail: "未登录" }, { status: 401 });
  }
  const res = await fetch(`${apiBase()}/api/auth/refresh`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return NextResponse.json(data, { status: res.status });
  }
  if (!data.token) {
    return NextResponse.json({ detail: "续期失败" }, { status: 401 });
  }
  await setSessionToken(data.token);
  return NextResponse.json(data);
}
