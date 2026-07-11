"use client";

import { QueryClient, useQuery } from "@tanstack/react-query";
import { api, BacktestResult, PortfolioInfo, Asset } from "./api";

/** 统一的 queryKey 工厂，便于精确失效。 */
export const qk = {
  portfolios: ["portfolios"] as const,
  assets: ["assets"] as const,
  result: (id: number | null, method?: string, benchmark?: string) =>
    ["portfolioResult", id ?? "demo", method ?? "default", benchmark ?? "default"] as const,
  resultRoot: (id: number | null) => ["portfolioResult", id ?? "demo"] as const,
};

const RESULT_STALE = 60_000;

/** 通过 react-query 缓存取回测结果；staleTime 内跨页/切换不重发。 */
export function fetchResult(
  client: QueryClient,
  id: number | null,
  method?: string,
  benchmark?: string,
): Promise<BacktestResult> {
  return client.fetchQuery({
    queryKey: qk.result(id, method, benchmark),
    queryFn: () => (id != null ? api.getResult(id, method, benchmark) : api.getDemo(undefined, method, benchmark)),
    staleTime: RESULT_STALE,
  });
}

/** 失效某组合(或 demo)的所有方法/基准结果缓存 + 组合列表。 */
export function invalidatePortfolio(client: QueryClient, id: number | null) {
  client.invalidateQueries({ queryKey: qk.resultRoot(id) });
  client.invalidateQueries({ queryKey: qk.portfolios });
}

export function usePortfolios() {
  return useQuery({
    queryKey: qk.portfolios,
    queryFn: () => api.listPortfolios().then((r) => r.portfolios),
    staleTime: RESULT_STALE,
  }) as { data?: PortfolioInfo[] };
}

export function useAssets() {
  return useQuery({
    queryKey: qk.assets,
    queryFn: () => api.getAssets().then((r) => r.assets),
    staleTime: 5 * 60_000,
  }) as { data?: Asset[] };
}
