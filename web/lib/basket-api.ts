/**
 * 一篮子资产模式的 API 客户端。
 *
 * 只读计算端点，不落库；请求经 Next rewrite 代理到 FastAPI。
 * 兼容两种响应包裹：生产契约的 `{ data: ... }` 与本地后端的裸对象。
 */

import { getToken } from "./api";
import type {
  BasketBacktestInput,
  BasketBacktestResult,
  BasketOptimizeInput,
  BasketOptimizeResult,
  StockIndustriesResponse,
  StockSearchResponse,
} from "./basket-types";

export class BasketApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "BasketApiError";
    this.status = status;
  }
}

function detailMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === "object") {
          const row = item as { msg?: string; loc?: unknown[] };
          const loc = Array.isArray(row.loc)
            ? row.loc.filter((x) => typeof x === "string" || typeof x === "number").at(-1)
            : undefined;
          return [loc, row.msg].filter((x) => x !== undefined && x !== "").join(": ");
        }
        return String(item);
      })
      .filter(Boolean)
      .join("；");
  }
  if (detail && typeof detail === "object") {
    const maybe = detail as { message?: unknown };
    if (maybe.message !== undefined) return detailMessage(maybe.message);
    try {
      return JSON.stringify(detail);
    } catch {
      return String(detail);
    }
  }
  return detail == null ? "" : String(detail);
}

function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown; message?: unknown };
      detail = body.detail ?? body.message ?? detail;
    } catch {
      /* 非 JSON 错误体：沿用 statusText */
    }
    const message = detailMessage(detail) || `请求失败（HTTP ${res.status}）`;
    throw new BasketApiError(message, res.status);
  }
  return (await res.json()) as T;
}

/** 生产契约 `{ data: ... }` 与裸对象都接受。 */
function unwrapData<T>(body: unknown): T {
  if (body && typeof body === "object" && "data" in body) {
    return (body as { data: T }).data;
  }
  return body as T;
}

export interface StockSearchQuery {
  q?: string;
  industry?: string | null;
  limit?: number;
  offset?: number;
}

export async function searchStocks(
  input: StockSearchQuery,
  signal?: AbortSignal,
): Promise<StockSearchResponse> {
  const qs = query({
    q: input.q?.trim() || undefined,
    industry: input.industry || undefined,
    limit: input.limit ?? 30,
    offset: input.offset ?? 0,
  });
  return requestJson<StockSearchResponse>(`/api/stocks/search${qs}`, {
    signal,
    cache: "no-store",
  });
}

export async function listStockIndustries(
  signal?: AbortSignal,
): Promise<StockIndustriesResponse> {
  return requestJson<StockIndustriesResponse>("/api/stocks/industries", {
    signal,
    cache: "no-store",
  });
}

export async function optimizeBasket(
  input: BasketOptimizeInput,
  signal?: AbortSignal,
): Promise<BasketOptimizeResult> {
  const body = await requestJson<unknown>("/api/basket/optimize", {
    method: "POST",
    body: JSON.stringify(input),
    signal,
  });
  return unwrapData<BasketOptimizeResult>(body);
}

export async function backtestBasket(
  input: BasketBacktestInput,
  signal?: AbortSignal,
): Promise<BasketBacktestResult> {
  const body = await requestJson<unknown>("/api/basket/backtest", {
    method: "POST",
    body: JSON.stringify(input),
    signal,
  });
  return unwrapData<BasketBacktestResult>(body);
}

export function basketErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}
