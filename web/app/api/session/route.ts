import { NextRequest, NextResponse } from "next/server";
import {
  apiBase,
  clearSessionToken,
  readSessionToken,
  setSessionToken,
} from "@/lib/session-server";

type LoginBody = {
  email: string;
  password: string;
  otp_code?: string;
};

export async function POST(request: NextRequest) {
  const body = (await request.json()) as LoginBody;
  const res = await fetch(`${apiBase()}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return NextResponse.json(data, { status: res.status });
  }
  if (data.requires_2fa && !data.token) {
    return NextResponse.json(data);
  }
  if (!data.token) {
    return NextResponse.json({ detail: "登录失败" }, { status: 401 });
  }
  await setSessionToken(data.token);
  return NextResponse.json(data);
}

export async function GET() {
  const token = await readSessionToken();
  if (!token) {
    return NextResponse.json({ detail: "未登录" }, { status: 401 });
  }
  const res = await fetch(`${apiBase()}/api/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const profile = await res.json().catch(() => ({}));
  if (!res.ok) {
    await clearSessionToken();
    return NextResponse.json(profile, { status: res.status });
  }
  return NextResponse.json({ ...profile, token });
}

export async function DELETE() {
  await clearSessionToken();
  return NextResponse.json({ ok: true });
}
