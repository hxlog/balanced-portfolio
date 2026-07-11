"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Trash2 } from "lucide-react";
import { api, AdminUser } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function AdminUsersPage() {
  const router = useRouter();
  const { isSuperAdmin, ready } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [savingLimit, setSavingLimit] = useState<string | null>(null);
  const [limits, setLimits] = useState<Record<string, number>>({});

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listUsers();
      setUsers(res.users);
      setLimits(Object.fromEntries(res.users.map((u) => [u.email, u.portfolio_limit ?? 3])));
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
    setBusy(true);
    try {
      await api.createUser(email.trim(), password);
      setEmail("");
      setPassword("");
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async (target: string) => {
    if (!window.confirm(`确认删除用户「${target}」?`)) return;
    setError(null);
    try {
      await api.deleteUser(target);
      await load();
    } catch (e) {
      setError(String(e));
    }
  };

  const onSaveLimit = async (target: string) => {
    setSavingLimit(target);
    setError(null);
    try {
      await api.updateUser(target, { portfolio_limit: limits[target] ?? 3 });
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setSavingLimit(null);
    }
  };

  if (!ready || !isSuperAdmin) {
    return <div className="p-12 text-center text-muted-foreground">加载中...</div>;
  }

  return (
    <div className="max-w-7xl mx-auto w-full p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">用户管理</h1>
        <p className="text-sm text-muted-foreground mt-1">
          超级管理员可分配白名单账号；白名单用户可新建/编辑/删除组合。
        </p>
      </div>

      {error && (
        <div className="bg-destructive/10 border border-destructive/30 text-destructive text-sm p-4 rounded-lg">
          {error}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">添加用户</CardTitle>
          <CardDescription>设置邮箱与初始密码</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col sm:flex-row gap-3">
          <Input placeholder="邮箱" value={email} onChange={(e) => setEmail(e.target.value)} className="sm:flex-1" />
          <Input type="password" placeholder="密码" value={password} onChange={(e) => setPassword(e.target.value)} className="sm:flex-1" />
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
                  <TableHead className="whitespace-nowrap">组合数</TableHead>
                  <TableHead className="min-w-[180px] whitespace-nowrap">组合上限</TableHead>
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
                    <TableCell className="font-mono">
                      {u.portfolio_count ?? 0}
                    </TableCell>
                    <TableCell>
                      {u.is_super_admin ? (
                        <span className="text-sm text-muted-foreground">不限</span>
                      ) : (
                        <div className="flex items-center gap-2">
                          <Input
                            type="number"
                            min={0}
                            value={limits[u.email] ?? u.portfolio_limit ?? 3}
                            onChange={(e) => setLimits((m) => ({ ...m, [u.email]: Number(e.target.value) }))}
                            className="w-20 h-8 font-mono"
                          />
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => onSaveLimit(u.email)}
                            disabled={savingLimit === u.email}
                          >
                            保存
                          </Button>
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {u.created_at ? u.created_at.slice(0, 19).replace("T", " ") : "-"}
                    </TableCell>
                    <TableCell className="text-right pr-0">
                      {!u.is_super_admin && (
                        <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive"
                          onClick={() => onDelete(u.email)}>
                          <Trash2 className="w-4 h-4 mr-1" /> 删除
                        </Button>
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
