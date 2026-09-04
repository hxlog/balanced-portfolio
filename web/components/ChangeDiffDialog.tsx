"use client";

import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export interface DiffRow {
  label: string;
  before: string;
  after: string;
}

export function ChangeDiffDialog({
  open, onOpenChange, diffs, assetSummary, canRecompute, busy, onMetaSave, onRecompute,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  diffs: DiffRow[];
  assetSummary: string | null;
  canRecompute: boolean;   // 有回测参数变更时允许重算入口
  busy: boolean;
  onMetaSave: () => void;
  onRecompute: () => void;
}) {
  const rows = assetSummary
    ? [...diffs, { label: "资产构成", before: "", after: assetSummary }]
    : diffs;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>确认变更</DialogTitle>
          <DialogDescription>
            以下为本次修改的参数。可仅保存（不重算回测），或保存并重新计算。
          </DialogDescription>
        </DialogHeader>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4">没有检测到参数变更。</p>
        ) : (
          <div className="max-h-[45vh] overflow-y-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[35%]">参数</TableHead>
                  <TableHead className="w-[32%]">变更前</TableHead>
                  <TableHead className="w-[32%]">变更后</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.label}>
                    <TableCell className="text-sm font-medium">{r.label}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{r.before || "—"}</TableCell>
                    <TableCell className="text-sm">{r.after}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        {canRecompute && (
          <p className="text-xs text-warning">
            含回测参数变更：仅保存不会更新回测结果，组合将标记为「待重算」。
          </p>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>取消</Button>
          <Button variant="outline" onClick={onMetaSave} disabled={busy || rows.length === 0}>
            {busy ? "保存中…" : "仅保存"}
          </Button>
          {canRecompute && (
            <Button onClick={onRecompute} disabled={busy}>
              {busy ? "提交中…" : "保存并重算"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
