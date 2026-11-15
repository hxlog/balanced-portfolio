"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Check,
  Download,
  Loader2,
  Plus,
  Search,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import type { Asset } from "@/lib/api";
import {
  NO_DATA_LABEL,
  RANGE_TONE_CLASS,
  formatRangeCN,
  rangeTone,
} from "@/lib/asset-range";
import { basketErrorMessage, listStockIndustries, searchStocks } from "@/lib/basket-api";
import {
  BASKET_ADJUST_OPTIONS,
  BASKET_CATEGORY_FILTERS,
  BASKET_MAX_ASSETS,
  STOCK_SOURCE,
  basketKey,
  type BasketAdjust,
  type BasketItem,
  type StockIndustry,
  type StockSearchItem,
} from "@/lib/basket-types";
import { cn } from "@/lib/utils";

const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  BASKET_CATEGORY_FILTERS.map((c) => [c.value, c.label]),
);

const STOCK_ADJUST_HINT = "仅切换本页展示口径，不影响回测；股票回测固定后复权（hfq）";

export function BasketAssets({
  items,
  onRemove,
  onAdjustChange,
  onOpenPool,
  onOpenStock,
  onIngest,
  ingestingKey,
  canManageAssets,
}: {
  items: BasketItem[];
  onRemove: (key: string) => void;
  onAdjustChange: (key: string, adjust: BasketAdjust) => void;
  onOpenPool: () => void;
  onOpenStock: () => void;
  onIngest: (item: BasketItem) => void;
  ingestingKey: string | null;
  canManageAssets: boolean;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <CardTitle className="text-base">篮子成分</CardTitle>
          <CardDescription>
            {items.length} / {BASKET_MAX_ASSETS} 项 · 点击资产行右侧的「不复权 / 前复权 / 后复权」仅切换展示口径
          </CardDescription>
        </div>
        <div className="flex w-full gap-2 sm:w-auto">
          <Button variant="outline" size="sm" className="flex-1 sm:flex-none" onClick={onOpenPool}>
            <Plus className="mr-1 h-4 w-4" />
            资产池
          </Button>
          <Button size="sm" className="flex-1 sm:flex-none" onClick={onOpenStock}>
            <Search className="mr-1 h-4 w-4" />
            搜索股票
          </Button>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        {items.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-bg-subtle/40 px-4 py-10 text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted">
              <Plus className="h-5 w-5 text-muted-foreground" />
            </div>
            <div>
              <p className="text-sm font-medium">先放入几个资产</p>
              <p className="mt-1 text-xs text-muted-foreground">
                从现有资产池选择，或搜索全 A 股；股票选中即按后复权口径加入。
              </p>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={onOpenPool}>
                资产池
              </Button>
              <Button size="sm" onClick={onOpenStock}>
                <Search className="mr-1 h-4 w-4" />
                搜索股票
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            {items.map((item, index) => {
              const awaitingData = item.inPool && !item.hasData;
              return (
                <div
                  key={item.key}
                  className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-border bg-background px-3 py-2.5"
                >
                  <span className="w-5 shrink-0 text-xs tabular-nums text-muted-foreground">
                    {index + 1}
                  </span>

                  <div className="min-w-0 flex-1 basis-[11rem]">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="truncate text-sm font-medium">{item.name}</span>
                      {item.category === "stock" && (
                        <Badge variant="secondary" className="shrink-0 px-1.5 font-normal">
                          股票
                        </Badge>
                      )}
                      {!item.inPool && (
                        <Badge
                          variant="outline"
                          className="shrink-0 border-warning/40 px-1.5 text-warning"
                        >
                          未接入
                        </Badge>
                      )}
                      {awaitingData && (
                        <Badge
                          variant="secondary"
                          className="shrink-0 px-1.5 font-normal text-muted-foreground"
                        >
                          待拉取
                        </Badge>
                      )}
                    </div>
                    <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
                      <span className="font-mono">{item.symbol}</span>
                      {item.industry && <span>{item.industry}</span>}
                      {item.market && <span>{item.market}</span>}
                      {!item.inPool && (
                        <span className="text-warning">
                          {canManageAssets ? "回测前需接入行情" : "需管理员接入行情"}
                        </span>
                      )}
                    </div>
                  </div>

                  <div
                    className="inline-flex shrink-0 overflow-hidden rounded-md border border-border bg-muted/40"
                    title={STOCK_ADJUST_HINT}
                    aria-label="展示复权口径"
                  >
                    {BASKET_ADJUST_OPTIONS.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        onClick={() => onAdjustChange(item.key, option.value)}
                        aria-pressed={item.adjustView === option.value}
                        title={`${option.label}（仅展示）`}
                        className={cn(
                          "px-1.5 py-1 text-[10px] font-medium uppercase tracking-wide transition-colors",
                          item.adjustView === option.value
                            ? "bg-background text-foreground shadow-sm"
                            : "text-muted-foreground hover:text-foreground",
                        )}
                      >
                        {option.value}
                      </button>
                    ))}
                  </div>

                  {!item.inPool && canManageAssets && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="shrink-0"
                      onClick={() => onIngest(item)}
                      disabled={ingestingKey === item.key}
                    >
                      {ingestingKey === item.key ? (
                        <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                      ) : (
                        <Download className="mr-1 h-4 w-4" />
                      )}
                      接入
                    </Button>
                  )}

                  <button
                    type="button"
                    onClick={() => onRemove(item.key)}
                    aria-label={`移除 ${item.name}`}
                    className="shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** 现有资产池选择器：与四象限 picker 同源（/api/assets），但点击即加入篮子。 */
export function AssetPoolDialog({
  open,
  onOpenChange,
  assets,
  selectedKeys,
  onPick,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  assets: Asset[];
  selectedKeys: ReadonlySet<string>;
  onPick: (asset: Asset) => void;
}) {
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("all");

  const filtered = useMemo(() => {
    const text = q.trim().toLowerCase();
    const rank = (asset: Asset): [number, number] => [
      asset.last_clean_date ? 0 : 1,
      (asset.currency ?? "CNY") !== "CNY" ? 1 : 0,
    ];
    return assets
      .filter(
        (asset) =>
          (category === "all" || asset.category === category) &&
          (text === "" ||
            (asset.name ?? "").toLowerCase().includes(text) ||
            asset.symbol.toLowerCase().includes(text)),
      )
      .slice()
      .sort((a, b) => {
        const ra = rank(a);
        const rb = rank(b);
        return (
          ra[0] - rb[0] ||
          ra[1] - rb[1] ||
          (a.name || a.symbol).localeCompare(b.name || b.symbol, "zh-CN")
        );
      });
  }, [assets, category, q]);

  const close = () => {
    onOpenChange(false);
    setQ("");
    setCategory("all");
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) close();
        else onOpenChange(true);
      }}
    >
      <DialogContent className="flex max-h-[85vh] w-[calc(100vw-2rem)] flex-col gap-3 overflow-hidden sm:max-w-2xl">
        <DialogHeader className="shrink-0">
          <DialogTitle>从资产池添加</DialogTitle>
          <DialogDescription>
            复用 /builder 现有资产池（指数、ETF、商品、债券与已接入股票）。
          </DialogDescription>
        </DialogHeader>

        <div className="grid shrink-0 grid-cols-[minmax(0,1fr)_9rem] gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={q}
              onChange={(event) => setQ(event.target.value)}
              placeholder="搜索名称或代码..."
              className="pl-8"
              autoFocus
            />
          </div>
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部类别</SelectItem>
              {BASKET_CATEGORY_FILTERS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="min-h-0 flex-1 space-y-1 overflow-auto pr-1">
          {filtered.map((asset) => {
            const key = basketKey(asset.symbol, asset.source);
            const picked = selectedKeys.has(key);
            const tone = rangeTone({
              firstDate: asset.first_clean_date,
              lastDate: asset.last_clean_date,
              isLagging: asset.is_lagging ?? asset.is_stale,
            });
            const range = formatRangeCN(asset.first_clean_date, asset.last_clean_date);
            return (
              <button
                key={key}
                type="button"
                disabled={picked}
                onClick={() => onPick(asset)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-md px-3 py-2 text-left transition-colors",
                  picked ? "cursor-default bg-accent/40" : "hover:bg-accent",
                )}
              >
                <div
                  className={cn(
                    "flex size-4 shrink-0 items-center justify-center rounded-[4px] border",
                    picked
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-input-background",
                  )}
                >
                  {picked && <Check className="h-3 w-3" />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="truncate text-sm">{asset.name || asset.symbol}</span>
                    {asset.category && (
                      <Badge variant="secondary" className="shrink-0 px-1.5 font-normal">
                        {CATEGORY_LABEL[asset.category] ?? asset.category}
                      </Badge>
                    )}
                    {picked && (
                      <span className="shrink-0 text-[11px] text-muted-foreground">
                        已加入
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-[11px] text-muted-foreground">
                    <span className="font-mono">{asset.symbol}</span>
                    {asset.vendor && <span>{asset.vendor}</span>}
                    {asset.source.startsWith("stock_") && <span>后复权</span>}
                  </div>
                </div>
                <span
                  className={cn(
                    "hidden w-[12.5rem] shrink-0 text-right text-[11px] tabular-nums whitespace-nowrap sm:inline-block",
                    RANGE_TONE_CLASS[tone],
                  )}
                >
                  {range ?? NO_DATA_LABEL}
                </span>
              </button>
            );
          })}
          {filtered.length === 0 && (
            <p className="px-3 py-8 text-center text-sm text-muted-foreground">
              没有匹配的资产
            </p>
          )}
        </div>

        <DialogFooter className="shrink-0 items-center gap-2 border-t border-border pt-3 sm:justify-between">
          <span className="text-xs text-muted-foreground">
            已加入 {selectedKeys.size} 项
          </span>
          <Button variant="ghost" onClick={close}>
            完成
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** 全 A 股搜索：选中即由父级加入篮子，并提示回测口径 = 后复权。 */
export function StockSearchDialog({
  open,
  onOpenChange,
  selectedKeys,
  poolKeys,
  onPick,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  selectedKeys: ReadonlySet<string>;
  poolKeys: ReadonlySet<string>;
  onPick: (stock: StockSearchItem) => void;
}) {
  const [q, setQ] = useState("");
  const [industry, setIndustry] = useState("all");
  const [industries, setIndustries] = useState<StockIndustry[]>([]);
  const [rows, setRows] = useState<StockSearchItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const enabled = q.trim().length > 0 || industry !== "all";

  useEffect(() => {
    if (!open || industries.length > 0) return;
    const controller = new AbortController();
    listStockIndustries(controller.signal)
      .then((res) => setIndustries(res.data))
      .catch(() => {
        /* 行业筛选拉取失败时仍可按代码/名称搜索 */
      });
    return () => controller.abort();
  }, [open, industries.length]);

  useEffect(() => {
    if (!open || !enabled) {
      setRows([]);
      setTotal(0);
      setError(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setLoading(true);
      setError(null);
      searchStocks(
        {
          q: q.trim(),
          industry: industry === "all" ? null : industry,
          limit: 30,
        },
        controller.signal,
      )
        .then((res) => {
          if (controller.signal.aborted) return;
          setRows(res.data);
          setTotal(res.meta.total);
        })
        .catch((err) => {
          if (controller.signal.aborted) return;
          setRows([]);
          setTotal(0);
          setError(basketErrorMessage(err));
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [enabled, industry, open, q]);

  const close = () => {
    onOpenChange(false);
    setQ("");
    setIndustry("all");
    setRows([]);
    setTotal(0);
    setError(null);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) close();
        else onOpenChange(true);
      }}
    >
      <DialogContent className="flex max-h-[85vh] w-[calc(100vw-2rem)] flex-col gap-3 overflow-hidden sm:max-w-2xl">
        <DialogHeader className="shrink-0">
          <DialogTitle>搜索 A 股</DialogTitle>
          <DialogDescription>
            全 A 股主数据 · 选中即加入篮子 · 回测口径 = 后复权（保持历史价格连续）
          </DialogDescription>
        </DialogHeader>

        <div className="grid shrink-0 grid-cols-[minmax(0,1fr)_10rem] gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={q}
              onChange={(event) => setQ(event.target.value)}
              placeholder="代码或名称，如 600036 / 招商银行"
              className="pl-8"
              autoFocus
            />
          </div>
          <Select value={industry} onValueChange={setIndustry}>
            <SelectTrigger className="w-full">
              <SelectValue placeholder="全部行业" />
            </SelectTrigger>
            <SelectContent className="max-h-72">
              <SelectItem value="all">全部行业</SelectItem>
              {industries.map((item) => (
                <SelectItem key={item.industry} value={item.industry}>
                  {item.industry}（{item.count}）
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="min-h-0 flex-1 space-y-1 overflow-auto pr-1">
          {loading && (
            <div className="space-y-1.5 py-1">
              {Array.from({ length: 5 }).map((_, index) => (
                <div key={index} className="flex items-center gap-3 px-3 py-2">
                  <div className="h-4 w-4 animate-pulse rounded bg-muted" />
                  <div className="h-4 flex-1 animate-pulse rounded bg-muted" />
                  <div className="h-3 w-16 animate-pulse rounded bg-muted" />
                </div>
              ))}
            </div>
          )}

          {!loading &&
            rows.map((stock) => {
              const key = basketKey(stock.stock_code, STOCK_SOURCE);
              const picked = selectedKeys.has(key);
              const inPool = poolKeys.has(key);
              return (
                <button
                  key={key}
                  type="button"
                  disabled={picked}
                  onClick={() => onPick(stock)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-md px-3 py-2 text-left transition-colors",
                    picked ? "cursor-default bg-accent/40" : "hover:bg-accent",
                  )}
                >
                  <div
                    className={cn(
                      "flex size-4 shrink-0 items-center justify-center rounded-[4px] border",
                      picked
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border bg-input-background",
                    )}
                  >
                    {picked && <Check className="h-3 w-3" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="truncate text-sm font-medium">{stock.name}</span>
                      {stock.is_st && (
                        <Badge variant="destructive" className="shrink-0 px-1.5">
                          ST
                        </Badge>
                      )}
                      {!inPool && (
                        <Badge
                          variant="outline"
                          className="shrink-0 border-warning/40 px-1.5 text-warning"
                        >
                          未接入
                        </Badge>
                      )}
                      {picked && (
                        <span className="shrink-0 text-[11px] text-muted-foreground">
                          已加入
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-muted-foreground">
                      <span className="font-mono">{stock.stock_code}</span>
                      {stock.market && <span>{stock.market}</span>}
                      {stock.industry_l1 && <span>{stock.industry_l1}</span>}
                    </div>
                  </div>
                  <span
                    className="hidden shrink-0 text-[11px] text-muted-foreground sm:inline"
                    title="后复权：以上市首日为基准复权，分红再投，回测默认口径"
                  >
                    后复权
                  </span>
                </button>
              );
            })}

          {!loading && !error && !enabled && (
            <div className="flex flex-col items-center justify-center gap-1 px-3 py-10 text-center">
              <Search className="h-6 w-6 text-muted-foreground" />
              <p className="mt-1 text-sm text-muted-foreground">
                输入股票代码或名称，或按行业筛选
              </p>
              <p className="text-xs text-muted-foreground">
                股票行情由新浪主源、腾讯备源接入，回测使用后复权。
              </p>
            </div>
          )}

          {!loading && !error && enabled && rows.length === 0 && (
            <p className="px-3 py-8 text-center text-sm text-muted-foreground">
              未找到匹配的股票
            </p>
          )}

          {!loading && error && (
            <div
              role="alert"
              className="mx-1 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
            >
              {error}
            </div>
          )}
        </div>

        <DialogFooter className="shrink-0 items-center gap-2 border-t border-border pt-3 sm:justify-between">
          <span className="text-xs text-muted-foreground">
            {enabled && total > 0
              ? `共 ${total} 条${total > rows.length ? `，显示前 ${rows.length} 条` : ""}`
              : "回测口径 = 后复权（历史价格连续，回测默认）"}
          </span>
          <Button variant="ghost" onClick={close}>
            完成
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** 供父级复用的轻提示：未接入股票选中后提醒如何补数据。 */
export function notifyStockAdded(
  stock: StockSearchItem,
  inPool: boolean,
): void {
  toast.success(`${stock.name} 已加入篮子 · 回测口径 = 后复权`, {
    id: "basket-stock-add",
    description: inPool
      ? undefined
      : "该股票尚未接入行情，回测前需在左侧点「接入」拉取历史数据",
  });
}
