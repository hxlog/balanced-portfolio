"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from "./ui/dialog";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger, SheetClose,
} from "./ui/sheet";
import { Moon, Sun, Github, LogOut, KeyRound, Menu, ShieldCheck } from "lucide-react";
import { useTheme } from "next-themes";
import QRCode from "qrcode";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";

const NAV_LINKS = [
  { href: "/dashboard", label: "风险平价回测" },
  { href: "/cffex", label: "股指期货看板" },
  { href: "/otc-derivatives-pricing", label: "场外衍生品定价" },
  { href: "/methodology", label: "方法论" },
] as const;

function navLinkClass(pathname: string, href: string) {
  return pathname === href
    || (href === "/dashboard" && pathname.startsWith("/dashboard"))
    || (href === "/otc-derivatives-pricing" && (pathname === "/otc-derivatives-pricing" || pathname === "/otc-pricing"))
    ? "text-foreground"
    : "text-muted-foreground hover:text-foreground";
}

export function Navbar() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const pathname = usePathname();
  const {
    email, isSuperAdmin, totpEnabled, mustSetup2fa,
    login, logout, changePassword, refresh,
  } = useAuth();

  useEffect(() => setMounted(true), []);

  const toggleTheme = () => {
    setTheme(resolvedTheme === "dark" ? "light" : "dark");
  };

  const links = [
    ...NAV_LINKS,
    ...(isSuperAdmin ? [
      { href: "/admin/assets" as const, label: "资产管理" },
      { href: "/admin/users" as const, label: "用户管理" },
    ] : []),
  ];

  return (
    <>
    {email && mustSetup2fa && (
      <Setup2faDialog open onOpenChange={() => {}} onDone={refresh} forced />
    )}
    <header className="sticky top-0 z-50 w-full border-b border-border bg-background/80 backdrop-blur-md">
      <div className="container mx-auto max-w-7xl px-4 sm:px-6 flex h-14 sm:h-16 items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
            <SheetTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="md:hidden shrink-0 text-muted-foreground hover:text-foreground"
                aria-label="打开菜单"
              >
                <Menu className="w-5 h-5" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-[min(100vw-2rem,20rem)] p-0 flex flex-col h-full">
              <SheetHeader className="border-b border-border px-5 py-4 text-left">
                <SheetTitle className="text-base font-semibold tracking-tight">Balanced Portfolio</SheetTitle>
              </SheetHeader>
              <nav className="flex flex-col px-3 py-3 gap-0.5">
                {links.map(({ href, label }) => (
                  <SheetClose asChild key={href}>
                    <Link
                      href={href}
                      className={`rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${navLinkClass(pathname, href)}`}
                    >
                      {label}
                    </Link>
                  </SheetClose>
                ))}
              </nav>
            </SheetContent>
          </Sheet>

          <Link href="/" className="font-bold tracking-tight text-base sm:text-lg flex items-center gap-2 shrink-0">
            <div className="w-6 h-6 rounded bg-primary text-primary-foreground flex items-center justify-center text-xs shrink-0">BP</div>
            <span className="hidden sm:inline whitespace-nowrap">Balanced Portfolio</span>
          </Link>

          <nav className="hidden md:flex items-center gap-6 text-sm font-medium ml-4">
            {links.map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                className={`transition-colors ${navLinkClass(pathname, href)}`}
              >
                {label}
              </Link>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-1.5 sm:gap-3 shrink-0">
          <Button variant="ghost" size="icon" asChild>
            <a
              href="https://github.com/hxlog/balanced-portfolio"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="在 GitHub 查看 Balanced Portfolio 源代码"
              title="GitHub"
              className="text-muted-foreground hover:text-foreground"
            >
              <Github className="w-4 h-4" />
            </a>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleTheme}
            className="text-muted-foreground hover:text-foreground"
            aria-label="切换主题"
          >
            {mounted && resolvedTheme === "dark" ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </Button>

          {email ? (
            <AccountMenu
              email={email}
              isSuperAdmin={isSuperAdmin}
              totpEnabled={totpEnabled}
              onLogout={logout}
              onChangePassword={changePassword}
              onRefresh={refresh}
            />
          ) : (
            <div className="flex items-center gap-1 sm:gap-2">
              <RegisterDialog />
              <LoginDialog onLogin={login} />
            </div>
          )}

        </div>
      </div>
    </header>
    </>
  );
}

function LoginDialog({ onLogin }: { onLogin: (e: string, p: string, otp?: string) => Promise<"ok" | "requires_2fa"> }) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [requires2fa, setRequires2fa] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setError(null);
    setBusy(true);
    try {
      const res = await onLogin(email, password, requires2fa ? otpCode : undefined);
      if (res === "requires_2fa") {
        setRequires2fa(true);
        setError(null);
        return;
      }
      setOpen(false);
      setPassword("");
      setOtpCode("");
      setRequires2fa(false);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">登录</Button>
      </DialogTrigger>
      <DialogContent className="max-w-sm">
        <DialogHeader><DialogTitle>用户登录</DialogTitle></DialogHeader>
        <div className="space-y-3">
          {error && <div className="text-sm text-destructive">{error}</div>}
          <Input placeholder="邮箱" value={email} onChange={(e) => setEmail(e.target.value)} />
          <Input type="password" placeholder="密码" value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()} />
          {requires2fa && (
            <Input
              placeholder="二次验证码"
              value={otpCode}
              onChange={(e) => setOtpCode(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
            />
          )}
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={busy || !email || !password || (requires2fa && !otpCode)}>
            {busy ? "登录中..." : requires2fa ? "验证并登录" : "登录"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function AccountMenu({
  email, isSuperAdmin, totpEnabled, onLogout, onChangePassword, onRefresh,
}: {
  email: string;
  isSuperAdmin: boolean;
  totpEnabled: boolean;
  onLogout: () => void;
  onChangePassword: (oldPw: string, newPw: string) => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [twoFaOpen, setTwoFaOpen] = useState(false);
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setMsg(null);
    setBusy(true);
    try {
      await onChangePassword(oldPw, newPw);
      setMsg("密码已修改");
      setOldPw(""); setNewPw("");
    } catch (e) {
      setMsg(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-1 sm:gap-2">
      <span className="hidden lg:inline text-xs text-muted-foreground max-w-[160px] truncate">{email}</span>
      <Button
        variant="ghost"
        size="icon"
        className={totpEnabled ? "text-primary" : "text-muted-foreground hover:text-foreground"}
        title={totpEnabled ? "两步验证已启用" : "启用两步验证"}
        onClick={() => setTwoFaOpen(true)}
      >
        <ShieldCheck className="w-4 h-4" />
      </Button>
      {totpEnabled ? (
        <TwoFaManageDialog
          open={twoFaOpen}
          onOpenChange={setTwoFaOpen}
          isSuperAdmin={isSuperAdmin}
          onDone={onRefresh}
        />
      ) : (
        <Setup2faDialog open={twoFaOpen} onOpenChange={setTwoFaOpen} onDone={onRefresh} />
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button variant="ghost" size="icon" className="text-muted-foreground hover:text-foreground" title="修改密码">
            <KeyRound className="w-4 h-4" />
          </Button>
        </DialogTrigger>
        <DialogContent className="max-w-sm">
          <DialogHeader><DialogTitle>修改密码</DialogTitle></DialogHeader>
          <div className="space-y-3">
            {msg && <div className="text-sm text-muted-foreground">{msg}</div>}
            <Input type="password" placeholder="原密码" value={oldPw} onChange={(e) => setOldPw(e.target.value)} />
            <Input type="password" placeholder="新密码" value={newPw} onChange={(e) => setNewPw(e.target.value)} />
          </div>
          <DialogFooter>
            <Button onClick={submit} disabled={busy || !oldPw || !newPw}>{busy ? "提交中..." : "确认修改"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Button variant="ghost" size="icon" className="text-muted-foreground hover:text-foreground" title="登出" onClick={onLogout}>
        <LogOut className="w-4 h-4" />
      </Button>
    </div>
  );
}

function Setup2faDialog({
  open, onOpenChange, onDone, forced,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onDone: () => void | Promise<void>;
  forced?: boolean;
}) {
  const [secret, setSecret] = useState("");
  const [qr, setQr] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setErr(null); setCode(""); setQr(null); setSecret(""); setLoading(true);
    api.setup2fa()
      .then(async (res) => {
        if (cancelled) return;
        setSecret(res.secret);
        try {
          setQr(await QRCode.toDataURL(res.otpauth_url, { margin: 1, width: 200 }));
        } catch {
          /* 二维码生成失败时仍可手动输入密钥 */
        }
      })
      .catch((e) => !cancelled && setErr(String(e instanceof Error ? e.message : e)))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [open]);

  const submit = async () => {
    setErr(null);
    setBusy(true);
    try {
      await api.verify2fa(code.trim());
      await onDone();
      onOpenChange(false);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v && forced) return; onOpenChange(v); }}>
      <DialogContent
        className="max-w-sm"
        onInteractOutside={forced ? (e) => e.preventDefault() : undefined}
        onEscapeKeyDown={forced ? (e) => e.preventDefault() : undefined}
      >
        <DialogHeader>
          <DialogTitle>{forced ? "管理员需绑定两步验证" : "启用两步验证 (2FA)"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          {forced && (
            <p className="text-sm text-muted-foreground">
              为保障账户安全，管理员必须绑定 TOTP 两步验证后才能继续操作。
            </p>
          )}
          <p className="text-sm text-muted-foreground">
            使用 Google Authenticator / 1Password / Microsoft Authenticator 扫描二维码，或手动输入密钥后，输入 6 位动态码完成绑定。
          </p>
          {loading ? (
            <div className="text-sm text-muted-foreground py-8 text-center">正在生成绑定信息…</div>
          ) : (
            <>
              {qr && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={qr} alt="两步验证二维码" width={200} height={200}
                  className="mx-auto rounded-lg border border-border bg-white p-1" />
              )}
              {secret && (
                <div className="text-center font-mono text-xs break-all bg-muted/40 rounded px-2 py-1">{secret}</div>
              )}
              <Input
                placeholder="输入 6 位验证码"
                value={code}
                inputMode="numeric"
                onChange={(e) => setCode(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submit()}
              />
              {err && <div className="text-sm text-destructive">{err}</div>}
            </>
          )}
        </div>
        <DialogFooter>
          {!forced && <Button variant="ghost" onClick={() => onOpenChange(false)}>取消</Button>}
          <Button onClick={submit} disabled={busy || loading || code.trim().length < 6}>
            {busy ? "验证中..." : "绑定"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

type TwoFaMode = "manage" | "rebind-verify" | "rebind-bind" | "disable";

function TwoFaManageDialog({
  open, onOpenChange, isSuperAdmin, onDone,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  isSuperAdmin: boolean;
  onDone: () => void | Promise<void>;
}) {
  const [mode, setMode] = useState<TwoFaMode>("manage");
  const [currentCode, setCurrentCode] = useState("");
  const [secret, setSecret] = useState("");
  const [qr, setQr] = useState<string | null>(null);
  const [newCode, setNewCode] = useState("");
  const [disableCode, setDisableCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setMode("manage");
    setCurrentCode("");
    setSecret("");
    setQr(null);
    setNewCode("");
    setDisableCode("");
    setErr(null);
    setBusy(false);
  };

  useEffect(() => {
    if (!open) reset();
  }, [open]);

  const startRebind = async () => {
    setErr(null);
    setBusy(true);
    try {
      const res = await api.setup2fa(currentCode.trim());
      setSecret(res.secret);
      try {
        setQr(await QRCode.toDataURL(res.otpauth_url, { margin: 1, width: 200 }));
      } catch {
        /* 二维码生成失败时仍可手动输入密钥 */
      }
      setMode("rebind-bind");
      setNewCode("");
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  const finishRebind = async () => {
    setErr(null);
    setBusy(true);
    try {
      await api.verify2fa(newCode.trim());
      await onDone();
      onOpenChange(false);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  const submitDisable = async () => {
    setErr(null);
    setBusy(true);
    try {
      await api.disable2fa(disableCode.trim());
      await onDone();
      onOpenChange(false);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { onOpenChange(v); if (!v) reset(); }}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>
            {mode === "manage" && "两步验证"}
            {mode === "rebind-verify" && "换绑两步验证"}
            {mode === "rebind-bind" && "扫描新验证器"}
            {mode === "disable" && "取消两步验证"}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          {mode === "manage" && (
            <>
              <div className="flex items-center gap-2 text-sm text-primary">
                <ShieldCheck className="w-4 h-4 shrink-0" />
                <span>两步验证已启用</span>
              </div>
              <p className="text-sm text-muted-foreground">
                登录时需输入验证器中的 6 位动态码。如需更换设备，可先换绑；普通用户也可取消绑定。
              </p>
              <div className="flex flex-col gap-2">
                <Button variant="outline" onClick={() => { setErr(null); setMode("rebind-verify"); }}>
                  换绑验证器
                </Button>
                {!isSuperAdmin && (
                  <Button variant="ghost" className="text-destructive hover:text-destructive"
                    onClick={() => { setErr(null); setMode("disable"); }}>
                    取消两步验证
                  </Button>
                )}
              </div>
            </>
          )}
          {mode === "rebind-verify" && (
            <>
              <p className="text-sm text-muted-foreground">请输入当前验证器中的 6 位码以继续换绑。</p>
              <Input
                placeholder="当前 6 位验证码"
                value={currentCode}
                inputMode="numeric"
                onChange={(e) => setCurrentCode(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && currentCode.trim().length >= 6 && startRebind()}
              />
            </>
          )}
          {mode === "rebind-bind" && (
            <>
              <p className="text-sm text-muted-foreground">
                使用验证器扫描新二维码，或手动输入密钥后输入新动态码完成换绑。
              </p>
              {qr && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={qr} alt="两步验证二维码" width={200} height={200}
                  className="mx-auto rounded-lg border border-border bg-white p-1" />
              )}
              {secret && (
                <div className="text-center font-mono text-xs break-all bg-muted/40 rounded px-2 py-1">{secret}</div>
              )}
              <Input
                placeholder="新验证器 6 位验证码"
                value={newCode}
                inputMode="numeric"
                onChange={(e) => setNewCode(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && newCode.trim().length >= 6 && finishRebind()}
              />
            </>
          )}
          {mode === "disable" && (
            <>
              <p className="text-sm text-muted-foreground">
                取消后登录将不再需要二次验证码。请输入当前验证器中的 6 位码确认。
              </p>
              <Input
                placeholder="当前 6 位验证码"
                value={disableCode}
                inputMode="numeric"
                onChange={(e) => setDisableCode(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && disableCode.trim().length >= 6 && submitDisable()}
              />
            </>
          )}
          {err && <div className="text-sm text-destructive">{err}</div>}
        </div>
        <DialogFooter>
          {mode !== "manage" && (
            <Button variant="ghost" onClick={() => { setErr(null); setMode("manage"); }}>
              返回
            </Button>
          )}
          {mode === "manage" && (
            <Button variant="ghost" onClick={() => onOpenChange(false)}>关闭</Button>
          )}
          {mode === "rebind-verify" && (
            <Button onClick={startRebind} disabled={busy || currentCode.trim().length < 6}>
              {busy ? "验证中..." : "下一步"}
            </Button>
          )}
          {mode === "rebind-bind" && (
            <Button onClick={finishRebind} disabled={busy || newCode.trim().length < 6}>
              {busy ? "验证中..." : "完成换绑"}
            </Button>
          )}
          {mode === "disable" && (
            <Button variant="destructive" onClick={submitDisable} disabled={busy || disableCode.trim().length < 6}>
              {busy ? "提交中..." : "确认取消"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RegisterDialog() {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">注册</Button>
      </DialogTrigger>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>账户注册</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 py-2 text-sm text-muted-foreground">
          <p>由于回测任务占用云服务器资源较多容易造成宕机，笔者云服务器资源有限，暂不开放注册与回测功能，但本产品永久免费且开源，你可以直接部署自己的实例。</p>
          <a
              href="https://github.com/hxlog/balanced-portfolio"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="在 GitHub 查看 Balanced Portfolio 源代码"
              title="GitHub"
              className="text-foreground underline underline-offset-4 hover:text-primary"
            >https://github.com/hxlog/balanced-portfolio</a>
          <hr></hr>
          <p>如需开通体验/讨论交流/开发，请联系刘星宇
            <br></br>
            微信号：<span className="font-mono text-foreground">MoreanOvO</span>，微信公众号：微信号：<span className="font-mono text-foreground">槐序的序章</span>。</p>
        </div>
        <DialogFooter>
          <Button onClick={() => setOpen(false)}>我知道了</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
