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

export interface AssetDiff {
  added: { label: string; quadrant: string }[];
  removed: { label: string; quadrant: string }[];
  moved: { label: string; from: string; to: string }[];
}

function AssetGroup({ title, className, children }: {
  title: string; className?: string; children: React.ReactNode;
}) {
  return (
    <div>
      <div className={`text-xs font-medium mb-1 ${className ?? ""}`}>{title}</div>
      <ul className="text-sm space-y-0.5">
        {children}
      </ul>
    </div>
  );
}

export function ChangeDiffDialog({
  open, onOpenChange, diffs, assetDiff, canRecompute, busy, onMetaSave, onRecompute,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  diffs: DiffRow[];
  assetDiff: AssetDiff | null;
  canRecompute: boolean;   // 有回测参数变更时允许重算入口
  busy: boolean;
  onMetaSave: () => void;
  onRecompute: () => void;
}) {
  const hasChange = diffs.length > 0 || assetDiff != null;
  // 资产分组网格: 只按已填充分组数定列(Tailwind 需静态字符串, 不满 3 组时避免挤在左侧)
  const filledCount = assetDiff
    ? [assetDiff.added.length, assetDiff.moved.length, assetDiff.removed.length].filter((n) => n > 0).length
    : 0;
  const gridCols =
    filledCount >= 3 ? "sm:grid-cols-3" : filledCount === 2 ? "sm:grid-cols-2" : "sm:grid-cols-1";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>确认变更</DialogTitle>
          <DialogDescription>
            以下为本次修改的参数。可仅保存（不重算回测），或保存并重新计算。
          </DialogDescription>
        </DialogHeader>
        {!hasChange ? (
          <p className="text-sm text-muted-foreground py-4">没有检测到参数变更。</p>
        ) : (
          <div className="max-h-[60vh] overflow-y-auto space-y-4">
            {diffs.length > 0 && (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[28%]">参数</TableHead>
                    <TableHead className="w-[36%]">变更前</TableHead>
                    <TableHead className="w-[36%]">变更后</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {diffs.map((r) => (
                    <TableRow key={r.label}>
                      <TableCell className="text-sm font-medium">{r.label}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{r.before || "—"}</TableCell>
                      <TableCell className="text-sm">{r.after}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            {assetDiff && (
              <div className="border border-border rounded-lg p-4 space-y-3">
                <div className="text-sm font-medium">资产构成变更</div>
                <div className={`grid grid-cols-1 ${gridCols} gap-3`}>
                  {assetDiff.added.length > 0 && (
                    <AssetGroup title={`新增 (${assetDiff.added.length})`} className="text-success">
                      {assetDiff.added.map((x, i) => (
                        <li key={i} className="text-sm">
                          {x.label}
                          <span className="text-muted-foreground"> → {x.quadrant}</span>
                        </li>
                      ))}
                    </AssetGroup>
                  )}
                  {assetDiff.moved.length > 0 && (
                    <AssetGroup title={`象限调整 (${assetDiff.moved.length})`} className="text-warning">
                      {assetDiff.moved.map((x, i) => (
                        <li key={i} className="text-sm">
                          {x.label}
                          <span className="text-muted-foreground"> （{x.from} → {x.to}）</span>
                        </li>
                      ))}
                    </AssetGroup>
                  )}
                  {assetDiff.removed.length > 0 && (
                    <AssetGroup title={`移除 (${assetDiff.removed.length})`} className="text-destructive">
                      {assetDiff.removed.map((x, i) => (
                        <li key={i} className="text-sm">
                          {x.label}
                          <span className="text-muted-foreground"> （{x.quadrant}）</span>
                        </li>
                      ))}
                    </AssetGroup>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
        {canRecompute && (
          <p className="text-xs text-warning">
            含回测参数变更：仅保存不会更新回测结果，组合将标记为「待重算」。
          </p>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>取消</Button>
          <Button variant="outline" onClick={onMetaSave} disabled={busy || !hasChange}>
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
