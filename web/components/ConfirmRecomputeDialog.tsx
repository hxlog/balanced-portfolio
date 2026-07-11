"use client";

import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Clock } from "lucide-react";

export function ConfirmRecomputeDialog({
  open,
  onOpenChange,
  onConfirm,
  title = "确认运行回测",
  confirmLabel = "确认并开始",
  busy = false,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onConfirm: () => void;
  title?: string;
  confirmLabel?: string;
  busy?: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-primary" />
            {title}
          </DialogTitle>
          <DialogDescription className="leading-relaxed pt-1">
            回测将重新计算 4 种优化方法，约需 <span className="text-foreground font-medium">2–10 分钟</span>
            （取决于回测周期与样本数量）。开始后不可中断；期间可切换查看其他组合，任务在后台运行。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>取消</Button>
          <Button onClick={onConfirm} disabled={busy}>{busy ? "提交中..." : confirmLabel}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
