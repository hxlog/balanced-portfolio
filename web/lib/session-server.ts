import { cookies } from "next/headers";

export const SESSION_COOKIE = "bp_session";
const DEFAULT_MAX_AGE_DAYS = 7;

export function sessionMaxAgeSeconds(): number {
  const days = Number(process.env.BP_SESSION_MAX_AGE_DAYS || DEFAULT_MAX_AGE_DAYS);
  if (!Number.isFinite(days) || days <= 0) return DEFAULT_MAX_AGE_DAYS * 24 * 60 * 60;
  return Math.floor(days * 24 * 60 * 60);
}

export function apiBase(): string {
  return process.env.BP_API_BASE || "http://127.0.0.1:8000";
}

export function sessionCookieOptions() {
  const secure = process.env.NODE_ENV === "production";
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure,
    path: "/",
    maxAge: sessionMaxAgeSeconds(),
  };
}

export async function readSessionToken(): Promise<string | null> {
  const jar = await cookies();
  return jar.get(SESSION_COOKIE)?.value ?? null;
}

/** 从 bp_session JWT 解出未验证 claims(sub/role)。
 *
 * 仅服务端用于默认组合分流等弱信任决策, 真实权限仍由 FastAPI 校验 token 签名;
 * 解码失败/无 payload 时返回 null, 不抛错。
 */
export async function readSessionClaims(): Promise<{ sub?: string; role?: string } | null> {
  const token = await readSessionToken();
  if (!token) return null;
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const parsed: unknown = JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
    if (typeof parsed !== "object" || parsed === null) return null;
    return parsed as { sub?: string; role?: string };
  } catch {
    return null;
  }
}

export async function setSessionToken(token: string): Promise<void> {
  const jar = await cookies();
  jar.set(SESSION_COOKIE, token, sessionCookieOptions());
}

export async function clearSessionToken(): Promise<void> {
  const jar = await cookies();
  jar.delete(SESSION_COOKIE);
}
