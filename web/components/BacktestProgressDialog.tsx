"use client";

import { useEffect, useRef, useState } from "react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Settings2 } from "lucide-react";
import { api } from "@/lib/api";

/**
 * 回测进度弹窗（非阻塞）。轮询 task 进度；用户可「后台运行」关闭弹窗，
 * 任务在服务端继续，不会被取消。
 */
export function BacktestProgressDialog({
  taskId,
  portfolioId,
  open,
  title = "正在运行回测",
  onDone,
  onOpenChange,
}: {
  taskId: string | null;
  portfolioId: number | null;
  open: boolean;
  title?: string;
  onDone: (portfolioId: number | null) => void;
  onOpenChange: (v: boolean) => void;
}) {
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState("排队中...");
  const [error, setError] = useState<string | null>(null);
  const cancelledRef = useRef(false);
  const doneRef = useRef(false);
  // onDone 是内联箭头, 身份每次渲染变化; 用 ref 避免 useEffect 反复重启轮询。
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    if (!open || !taskId) return;
    cancelledRef.current = false;
    doneRef.current = false;
    setProgress(0);
    setMessage("排队中...");
    setError(null);

    void api.waitForTask(taskId, {
      intervalMs: 2000,
      onPoll: (st) => {
        if (cancelledRef.current) return;
        const pct = st.progress_total > 0
          ? Math.round((st.progress_current / st.progress_total) * 100)
          : 0;
        setProgress(Math.max(0, Math.min(100, pct)));
        setMessage(st.progress_message || "回测进行中，预计算 4 种优化方法...");
      },
      onTransientError: (_e, count) => {
        if (cancelledRef.current) return;
        setMessage(`任务仍在后台运行，状态同步失败第 ${count} 次，正在继续等待...`);
      },
    })
      .then(() => {
        if (cancelledRef.current || doneRef.current) return;
        doneRef.current = true;
        setProgress(100);
        // 先关闭弹窗: 避免缓存组件重新激活时 open=true 对已完成任务再次 resolve 触发导航劫持。
        onOpenChange(false);
        onDoneRef.current(portfolioId);
      })
      .catch((e) => {
        if (cancelledRef.current || doneRef.current) return;
        setError(String(e instanceof Error ? e.message : e));
      });

    return () => { cancelledRef.current = true; };
    // 依赖里不含 onDone(用 ref), 避免父渲染导致轮询反复重启。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, taskId, portfolioId]);

  const runInBackground = () => {
    cancelledRef.current = true;
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) runInBackground(); }}>
      <DialogContent
        className="max-w-sm"
        onInteractOutside={(e) => e.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Settings2 className={`w-4 h-4 text-primary ${error ? "" : "animate-spin"}`} />
            {title}
          </DialogTitle>
          <DialogDescription className="sr-only">回测进度</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-1">
          {error ? (
            <p className="text-sm text-destructive">{error}</p>
          ) : (
            <>
              <p className="text-sm text-muted-foreground min-h-[2.5rem]">{message}</p>
              <div className="h-2 bg-muted rounded-full overflow-hidden">
                <div className="h-full bg-primary transition-all" style={{ width: `${progress}%` }} />
              </div>
              <p className="text-xs text-muted-foreground text-right">{progress}%</p>
            </>
          )}
        </div>
        <DialogFooter>
          {error ? (
            <Button variant="outline" onClick={() => onOpenChange(false)}>关闭</Button>
          ) : (
            <Button variant="outline" onClick={runInBackground}>后台运行，去看其他组合</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
