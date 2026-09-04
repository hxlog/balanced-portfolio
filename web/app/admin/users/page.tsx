"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Trash2, ShieldCheck } from "lucide-react";
import { api, AdminUser } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function AdminUsersPage() {
  const router = useRouter();
  const { isSuperAdmin, ready } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newAssetEdit, setNewAssetEdit] = useState(false);
  const [newLimitUnlimited, setNewLimitUnlimited] = useState(false);
  const [newLimit, setNewLimit] = useState("3");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [savingLimit, setSavingLimit] = useState<string | null>(null);
  // null = 无限(后端 portfolio_limit 为 NULL); number = 有限上限。
  // 行内输入框只在非 null 时渲染; 「设上限」写入 3 即切换为输入模式, load() 后回到服务端真值。
  const [limits, setLimits] = useState<Record<string, number | null>>({});
  const [savingAssetEdit, setSavingAssetEdit] = useState<string | null>(null);
  const [saveOk, setSaveOk] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listUsers();
      setUsers(res.users);
      // null 保留为无限, 不回退 3
      setLimits(Object.fromEntries(res.users.map((u) => [u.email, u.portfolio_limit ?? null])));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!ready) return;
    if (!isSuperAdmin) {
      router.replace("/dashboard");
      return;
    }
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, isSuperAdmin]);

  const onCreate = async () => {
    setError(null);
    const limit = newLimitUnlimited ? null : Math.floor(Number(newLimit));
    if (!newLimitUnlimited && (newLimit.trim() === "" || limit == null || !Number.isFinite(limit) || limit < 0)) {
      setError("组合上限须为非负整数或无限");
      return;
    }
    setBusy(true);
    try {
      await api.createUser(email.trim(), password, {
        portfolio_limit: limit,
        can_manage_assets: newAssetEdit,
      });
      setEmail("");
      setPassword("");
      setNewAssetEdit(false);
      setNewLimitUnlimited(false);
      setNewLimit("3");
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  // 删除确认由行内 AlertDialog 承担; 此处只执行删除。
  const onDelete = async (target: string) => {
    setError(null);
    try {
      await api.deleteUser(target);
      await load();
    } catch (e) {
      setError(String(e));
    }
  };

  const onSaveLimit = async (target: string) => {
    const raw = limits[target];
    const portfolio_limit = raw == null ? NaN : Math.trunc(raw);
    if (!Number.isFinite(portfolio_limit) || portfolio_limit < 0) {
      setError("组合上限须为非负整数");
      setSaveOk(null);
      return;
    }
    setSavingLimit(target);
    setError(null);
    setSaveOk(null);
    try {
      // 本路径只发送已校验的非负整数; 无限走「设为无限」(显式 null)
      const res = await api.updateUser(target, { portfolio_limit });
      setLimits((m) => ({ ...m, [target]: res.portfolio_limit }));
      setSaveOk(`${res.email} 组合上限已更新为 ${res.portfolio_limit ?? "不限"}`);
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setSavingLimit(null);
    }
  };

  const onSetUnlimited = async (target: string) => {
    setSavingLimit(target);
    setError(null);
    setSaveOk(null);
    try {
      const res = await api.updateUser(target, { portfolio_limit: null });
      setLimits((m) => ({ ...m, [target]: null }));
      setSaveOk(`${res.email} 组合上限已设为不限`);
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setSavingLimit(null);
    }
  };

  const onToggleAssetEdit = async (target: string, next: boolean) => {
    setSavingAssetEdit(target);
    setError(null);
    setSaveOk(null);
    try {
      await api.updateUser(target, { can_manage_assets: next });
      setSaveOk(`${target} 资产编辑权限已${next ? "授予" : "收回"}`);
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setSavingAssetEdit(null);
    }
  };

  if (!ready || !isSuperAdmin) {
    return <div className="p-12 text-center text-muted-foreground">加载中...</div>;
  }

  return (
    <div className="max-w-7xl mx-auto w-full p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">用户管理</h1>
        <p className="text-sm text-muted-foreground mt-1">
          超级管理员可分配白名单账号；白名单用户可新建/编辑/删除组合。
        </p>
      </div>

      {error && (
        <div className="bg-destructive/10 border border-destructive/30 text-destructive text-sm p-4 rounded-lg">
          {error}
        </div>
      )}
      {saveOk && (
        <div className="bg-emerald-500/10 border border-emerald-500/30 text-emerald-700 dark:text-emerald-300 text-sm p-4 rounded-lg">
          {saveOk}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">添加用户</CardTitle>
          <CardDescription>设置邮箱、初始密码、资产编辑权限与组合上限（上限可设为无限）</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col sm:flex-row gap-3">
          <Input placeholder="邮箱" value={email} onChange={(e) => setEmail(e.target.value)} className="sm:flex-1" />
          <Input type="password" placeholder="密码" value={password} onChange={(e) => setPassword(e.target.value)} className="sm:flex-1" />
          <div className="flex items-center gap-2 text-sm">
            <Switch checked={newAssetEdit} onCheckedChange={setNewAssetEdit} aria-label="资产编辑权限" />
            <span>资产编辑</span>
            <span className="text-xs text-muted-foreground">（可进 /admin/assets 新增/更新/测试/拉取增量）</span>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <span className="whitespace-nowrap">组合上限</span>
            <Input
              type="number"
              min={0}
              step={1}
              className="w-20 h-8 font-mono"
              value={newLimit}
              onChange={(e) => setNewLimit(e.target.value)}
              disabled={newLimitUnlimited}
              aria-label="组合上限"
            />
            <label className="flex items-center gap-1.5 whitespace-nowrap">
              <Checkbox
                checked={newLimitUnlimited}
                onCheckedChange={(v) => setNewLimitUnlimited(v === true)}
              />
              无限
            </label>
          </div>
          <Button onClick={onCreate} disabled={busy || !email.trim() || !password}>添加</Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">白名单用户</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          {loading ? (
            <p className="text-sm text-muted-foreground">加载中...</p>
          ) : (
            <Table className="min-w-[900px]">
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-0 min-w-[200px] whitespace-nowrap">邮箱</TableHead>
                  <TableHead className="whitespace-nowrap">角色</TableHead>
                  <TableHead className="whitespace-nowrap">资产编辑</TableHead>
                  <TableHead className="whitespace-nowrap">组合数</TableHead>
                  <TableHead className="min-w-[280px] whitespace-nowrap">组合上限</TableHead>
                  <TableHead className="whitespace-nowrap">创建时间</TableHead>
                  <TableHead className="text-right pr-0 whitespace-nowrap">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.map((u) => (
                  <TableRow key={u.email}>
                    <TableCell className="pl-0 font-medium whitespace-nowrap">{u.email}</TableCell>
                    <TableCell>
                      {u.is_super_admin ? (
                        <Badge variant="secondary">超级管理员</Badge>
                      ) : (
                        <Badge variant="outline">白名单</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      {u.is_super_admin ? (
                        <span className="inline-flex items-center gap-1 text-sm text-muted-foreground">
                          <ShieldCheck className="w-4 h-4" /> 恒有
                        </span>
                      ) : (
                        <Button
                          type="button"
                          variant={u.can_manage_assets ? "outline" : "ghost"}
                          size="sm"
                          onClick={() => onToggleAssetEdit(u.email, !u.can_manage_assets)}
                          disabled={savingAssetEdit === u.email}
                          className={u.can_manage_assets ? "text-primary border-primary/40" : "text-muted-foreground"}
                          title="授予后该用户可进 /admin/assets 新增/更新/测试/拉取增量(不可删除、停用、全量拉取)"
                        >
                          {u.can_manage_assets ? "已授权" : "未授权"}
                        </Button>
                      )}
                    </TableCell>
                    <TableCell className="font-mono">
                      {u.portfolio_count ?? 0}
                    </TableCell>
                    <TableCell>
                      {u.is_super_admin ? (
                        <span className="text-sm text-muted-foreground">不限</span>
                      ) : limits[u.email] == null ? (
                        <div className="flex items-center gap-2">
                          <Badge variant="secondary">不限</Badge>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => setLimits((m) => ({ ...m, [u.email]: 3 }))}
                            disabled={savingLimit === u.email}
                          >
                            设上限
                          </Button>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2">
                          <Input
                            id={`portfolio-limit-${u.email}`}
                            name={`portfolio_limit_${u.email}`}
                            type="number"
                            min={0}
                            step={1}
                            value={limits[u.email] ?? 3}
                            onChange={(e) => {
                              const n = Number(e.target.value);
                              setLimits((m) => ({
                                ...m,
                                [u.email]: Number.isFinite(n) ? Math.trunc(n) : 0,
                              }));
                            }}
                            className="w-20 h-8 font-mono"
                          />
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => onSaveLimit(u.email)}
                            disabled={savingLimit === u.email}
                          >
                            保存
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="text-muted-foreground"
                            onClick={() => onSetUnlimited(u.email)}
                            disabled={savingLimit === u.email}
                            title="清除上限, 该用户可创建任意数量组合"
                          >
                            设为无限
                          </Button>
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {u.created_at ? u.created_at.slice(0, 19).replace("T", " ") : "-"}
                    </TableCell>
                    <TableCell className="text-right pr-0">
                      {!u.is_super_admin && (
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive">
                              <Trash2 className="w-4 h-4 mr-1" /> 删除
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>确认删除用户「{u.email}」？</AlertDialogTitle>
                              <AlertDialogDescription>
                                将移除该用户的登录与组合操作权限，其已创建的组合保留。此操作不可在界面上撤销。
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>取消</AlertDialogCancel>
                              <AlertDialogAction
                                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                                onClick={() => void onDelete(u.email)}
                              >
                                确认删除
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
