"use client";

import { createContext, useContext, useEffect, useState, ReactNode, useCallback } from "react";
import { api, getToken, setToken, AuthProfile, shouldRefreshToken } from "./api";

interface AuthState {
  userId: number | null;
  email: string | null;
  /** 任意已登录白名单用户：可创建/编辑自己的组合 */
  isWhitelisted: boolean;
  /** 真实管理员：可见全部组合、管理用户/资产/示例 */
  isSuperAdmin: boolean;
  role: string | null;
  /** 是否已绑定 TOTP 两步验证 */
  totpEnabled: boolean;
  /** 管理员尚未绑定 TOTP，需强制绑定 */
  mustSetup2fa: boolean;
  ready: boolean;
  login: (email: string, password: string, otpCode?: string) => Promise<"ok" | "requires_2fa">;
  logout: () => void;
  changePassword: (oldPw: string, newPw: string) => Promise<void>;
  /** 重新拉取当前用户资料(如绑定 2FA 后刷新状态) */
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

const EMAIL_KEY = "bp_email";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [email, setEmail] = useState<string | null>(null);
  const [userId, setUserId] = useState<number | null>(null);
  const [isWhitelisted, setIsWhitelisted] = useState(false);
  const [isSuperAdmin, setIsSuperAdmin] = useState(false);
  const [role, setRole] = useState<string | null>(null);
  const [totpEnabled, setTotpEnabled] = useState(false);
  const [mustSetup2fa, setMustSetup2fa] = useState(false);
  const [ready, setReady] = useState(false);

  const clearSession = useCallback(() => {
    setToken(null);
    window.localStorage.removeItem(EMAIL_KEY);
    setEmail(null);
    setUserId(null);
    setIsWhitelisted(false);
    setIsSuperAdmin(false);
    setRole(null);
    setTotpEnabled(false);
    setMustSetup2fa(false);
  }, []);

  const applyProfile = useCallback((profile: AuthProfile) => {
    setUserId(profile.user_id ?? null);
    setEmail(profile.email);
    window.localStorage.setItem(EMAIL_KEY, profile.email);
    setIsWhitelisted(!!profile.is_whitelisted);
    setIsSuperAdmin(!!profile.is_super_admin);
    setRole(profile.role ?? null);
    setTotpEnabled(!!profile.totp_enabled);
    setMustSetup2fa(!!profile.must_setup_2fa);
  }, []);

  const maybeRefreshToken = useCallback(async () => {
    const token = getToken();
    if (!shouldRefreshToken(token)) return;
    try {
      const res = await api.refreshSession();
      if (res.token) setToken(res.token);
    } catch {
      /* 续期失败时保留当前 token，由后续 401 处理 */
    }
  }, []);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      try {
        const restored = await api.restoreSession();
        if (restored.token) setToken(restored.token);
        applyProfile(restored);
        return;
      } catch {
        clearSession();
        return;
      }
    }
    try {
      const profile = await api.me();
      applyProfile(profile);
      await maybeRefreshToken();
    } catch {
      try {
        const restored = await api.restoreSession();
        if (restored.token) setToken(restored.token);
        applyProfile(restored);
      } catch {
        clearSession();
      }
    }
  }, [applyProfile, clearSession, maybeRefreshToken]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (getToken()) {
          const profile = await api.me();
          if (!cancelled) {
            applyProfile(profile);
            await maybeRefreshToken();
          }
        } else {
          const restored = await api.restoreSession();
          if (!cancelled) {
            if (restored.token) setToken(restored.token);
            applyProfile(restored);
          }
        }
      } catch {
        if (!cancelled) clearSession();
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => { cancelled = true; };
  }, [applyProfile, clearSession, maybeRefreshToken]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      if (getToken()) {
        void maybeRefreshToken();
        return;
      }
      void api.restoreSession()
        .then((restored) => {
          if (restored.token) setToken(restored.token);
          applyProfile(restored);
        })
        .catch(() => undefined);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [maybeRefreshToken, applyProfile]);

  const login = async (e: string, p: string, otpCode?: string) => {
    const res = await api.login(e, p, otpCode);
    if (res.requires_2fa && !res.token) {
      return "requires_2fa";
    }
    if (!res.token) throw new Error("登录失败");
    setToken(res.token);
    const profile = await api.me();
    applyProfile(profile);
    return "ok";
  };

  const logout = () => {
    void api.logoutSession().catch(() => undefined);
    clearSession();
  };

  const changePassword = async (oldPw: string, newPw: string) => {
    await api.changePassword(oldPw, newPw);
  };

  return (
    <AuthContext.Provider
      value={{
        userId, email, isWhitelisted, isSuperAdmin, role, totpEnabled, mustSetup2fa,
        ready, login, logout, changePassword, refresh,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return ctx;
}
