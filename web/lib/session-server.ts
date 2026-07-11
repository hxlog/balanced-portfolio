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

export async function setSessionToken(token: string): Promise<void> {
  const jar = await cookies();
  jar.set(SESSION_COOKIE, token, sessionCookieOptions());
}

export async function clearSessionToken(): Promise<void> {
  const jar = await cookies();
  jar.delete(SESSION_COOKIE);
}
