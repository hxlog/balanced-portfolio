/**
 * Binance 代理 Worker — 完全离线单元测试（不访问网络、不依赖 wrangler runtime）。
 *
 * 运行: node --test test/*.test.ts
 * 说明: Node 24 原生 TypeScript type-stripping 直接执行 .ts，无需编译步骤。
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  ALLOWED_PATHS,
  BINANCE_BASE,
  CACHE_SECONDS,
  DEFAULT_ALLOWED_ORIGIN,
  FixedWindowRateLimiter,
  buildUpstreamUrl,
  corsHeaders,
  handleRequest,
  isAllowedPath,
} from "../src/index.ts";
import type { CacheLike, HandlerDeps } from "../src/index.ts";

const ORIGIN = "https://xushilu.com";

class MemoryCache implements CacheLike {
  readonly store = new Map<string, Response>();

  async match(request: Request): Promise<Response | undefined> {
    return this.store.get(request.url)?.clone();
  }

  async put(request: Request, response: Response): Promise<void> {
    this.store.set(request.url, response.clone());
  }
}

function request(path: string, query = "", headers: Record<string, string> = {}): Request {
  return new Request(
    `https://bp-proxy.example.workers.dev/?path=${encodeURIComponent(path)}${query}`,
    { headers: { "CF-Connecting-IP": "203.0.113.7", Origin: ORIGIN, ...headers } },
  );
}

function deps(overrides: Partial<HandlerDeps> = {}): HandlerDeps {
  return {
    limiter: new FixedWindowRateLimiter(),
    cache: new MemoryCache(),
    fetchImpl: async () =>
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    now: () => 1_700_000_000_000,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// 白名单
// ---------------------------------------------------------------------------

test("ALLOWED_PATHS contains the public market-data plus contract-discovery endpoints", () => {
  assert.deepEqual(
    [...ALLOWED_PATHS].sort(),
    [
      "/fapi/v1/exchangeInfo",
      "/fapi/v1/openInterest",
      "/fapi/v1/premiumIndex",
      "/fapi/v1/ticker/24hr",
      "/futures/data/globalLongShortAccountRatio",
      "/futures/data/openInterestHist",
      "/futures/data/takerlongshortRatio",
    ].sort(),
  );
});

test("isAllowedPath rejects private, traversal and prefix-confusion paths", () => {
  assert.equal(isAllowedPath("/fapi/v1/premiumIndex"), true);
  assert.equal(isAllowedPath("/fapi/v1/account"), false);
  assert.equal(isAllowedPath("/sapi/v1/account"), false);
  assert.equal(isAllowedPath("/fapi/v1/premiumIndex/../../account"), false);
  assert.equal(isAllowedPath("/fapi/v1/premiumIndexX"), false);
  assert.equal(isAllowedPath(""), false);
});

// ---------------------------------------------------------------------------
// 上游 URL / 查询透传
// ---------------------------------------------------------------------------

test("buildUpstreamUrl forwards allowed query params and drops path", () => {
  const params = new URLSearchParams(
    "path=/futures/data/openInterestHist&symbol=BTCUSDT&period=5m&limit=1",
  );

  const url = buildUpstreamUrl("/futures/data/openInterestHist", params);

  assert.equal(
    url,
    `${BINANCE_BASE}/futures/data/openInterestHist?symbol=BTCUSDT&period=5m&limit=1`,
  );
  assert.equal(url.includes("path="), false);
});

test("buildUpstreamUrl works without query params", () => {
  assert.equal(
    buildUpstreamUrl("/fapi/v1/premiumIndex", new URLSearchParams()),
    `${BINANCE_BASE}/fapi/v1/premiumIndex`,
  );
});

// ---------------------------------------------------------------------------
// CORS
// ---------------------------------------------------------------------------

test("corsHeaders allows only https://xushilu.com", () => {
  assert.equal(DEFAULT_ALLOWED_ORIGIN, "https://xushilu.com");
  assert.equal(
    corsHeaders(ORIGIN)["Access-Control-Allow-Origin"],
    "https://xushilu.com",
  );
  assert.equal(
    corsHeaders("https://evil.example")["Access-Control-Allow-Origin"],
    undefined,
  );
  assert.equal(corsHeaders(null)["Access-Control-Allow-Origin"], undefined);
});

test("OPTIONS preflight returns 204 with CORS headers", async () => {
  const response = await handleRequest(
    new Request("https://bp-proxy.example.workers.dev/?path=/fapi/v1/premiumIndex", {
      method: "OPTIONS",
      headers: { Origin: ORIGIN },
    }),
    {},
    undefined,
    deps(),
  );

  assert.equal(response.status, 204);
  assert.equal(response.headers.get("Access-Control-Allow-Origin"), ORIGIN);
});

// ---------------------------------------------------------------------------
// 限频
// ---------------------------------------------------------------------------

test("FixedWindowRateLimiter allows 120 requests per minute then returns 429 info", () => {
  const limiter = new FixedWindowRateLimiter(120, 60_000);
  const t0 = 1_700_000_000_000;

  for (let i = 0; i < 120; i += 1) {
    assert.equal(limiter.allow("1.2.3.4", t0 + i).allowed, true);
  }
  const blocked = limiter.allow("1.2.3.4", t0 + 120);
  assert.equal(blocked.allowed, false);
  assert.equal(blocked.retryAfter, 60);
  // 另一个 IP 不受影响
  assert.equal(limiter.allow("5.6.7.8", t0 + 120).allowed, true);
  // 下一分钟窗口重置
  assert.equal(limiter.allow("1.2.3.4", t0 + 60_001).allowed, true);
});

// ---------------------------------------------------------------------------
// 请求校验
// ---------------------------------------------------------------------------

test("handler rejects missing path with 400", async () => {
  const response = await handleRequest(
    new Request("https://bp-proxy.example.workers.dev/"),
    {},
    undefined,
    deps(),
  );
  assert.equal(response.status, 400);
  assert.deepEqual(await response.json(), { error: { code: "missing_path" } });
});

test("handler rejects non-whitelisted path with 403", async () => {
  const response = await handleRequest(
    request("/fapi/v1/account"),
    {},
    undefined,
    deps(),
  );
  assert.equal(response.status, 403);
  assert.deepEqual(await response.json(), { error: { code: "path_not_allowed" } });
});

test("handler rejects missing symbol for symbol-scoped endpoints", async () => {
  for (const path of [
    "/fapi/v1/openInterest",
    "/futures/data/globalLongShortAccountRatio",
    "/futures/data/takerlongshortRatio",
    "/futures/data/openInterestHist",
  ]) {
    const response = await handleRequest(request(path), {}, undefined, deps());
    assert.equal(response.status, 400, path);
    assert.deepEqual(await response.json(), { error: { code: "missing_symbol" } });
  }
});

test("handler rejects non-GET methods with 405", async () => {
  const response = await handleRequest(
    new Request("https://bp-proxy.example.workers.dev/?path=/fapi/v1/premiumIndex", {
      method: "POST",
    }),
    {},
    undefined,
    deps(),
  );
  assert.equal(response.status, 405);
});

// ---------------------------------------------------------------------------
// 转发 / 缓存
// ---------------------------------------------------------------------------

test("handler forwards query params and returns upstream JSON", async () => {
  let seenUrl = "";
  const response = await handleRequest(
    request("/futures/data/openInterestHist", "&symbol=BTCUSDT&period=5m&limit=1"),
    {},
    undefined,
    deps({
      fetchImpl: async (input) => {
        seenUrl = String(input);
        return new Response(JSON.stringify([{ symbol: "BTCUSDT" }]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      },
    }),
  );

  assert.equal(seenUrl, `${BINANCE_BASE}/futures/data/openInterestHist?symbol=BTCUSDT&period=5m&limit=1`);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), [{ symbol: "BTCUSDT" }]);
  assert.equal(response.headers.get("Access-Control-Allow-Origin"), ORIGIN);
  assert.equal(response.headers.get("Cache-Control"), `public, max-age=${CACHE_SECONDS}`);
});

test("handler serves second request from caches.default without refetching", async () => {
  const cache = new MemoryCache();
  let calls = 0;
  const sharedDeps = deps({
    cache,
    fetchImpl: async () => {
      calls += 1;
      return new Response(JSON.stringify({ call: calls }), { status: 200 });
    },
  });

  const first = await handleRequest(
    request("/fapi/v1/premiumIndex", "&symbol=BTCUSDT"),
    {},
    undefined,
    sharedDeps,
  );
  const second = await handleRequest(
    request("/fapi/v1/premiumIndex", "&symbol=BTCUSDT"),
    {},
    undefined,
    sharedDeps,
  );

  assert.equal(calls, 1);
  assert.deepEqual(await first.json(), { call: 1 });
  assert.deepEqual(await second.json(), { call: 1 });
  assert.equal(second.headers.get("Access-Control-Allow-Origin"), ORIGIN);
});

test("handler does not cache upstream errors", async () => {
  const cache = new MemoryCache();
  let calls = 0;
  const sharedDeps = deps({
    cache,
    fetchImpl: async () => {
      calls += 1;
      return new Response("rate limited", { status: 429 });
    },
  });

  const first = await handleRequest(request("/fapi/v1/premiumIndex"), {}, undefined, sharedDeps);
  const second = await handleRequest(request("/fapi/v1/premiumIndex"), {}, undefined, sharedDeps);

  assert.equal(first.status, 429);
  assert.equal(second.status, 429);
  assert.equal(calls, 2);
  assert.equal(cache.store.size, 0);
});

test("handler returns 502 when upstream fetch throws", async () => {
  const response = await handleRequest(
    request("/fapi/v1/premiumIndex"),
    {},
    undefined,
    deps({
      fetchImpl: async () => {
        throw new Error("network down");
      },
    }),
  );

  assert.equal(response.status, 502);
  assert.deepEqual(await response.json(), { error: { code: "upstream_unreachable" } });
});

test("handler returns 429 with Retry-After once per-IP budget is exhausted", async () => {
  const limiter = new FixedWindowRateLimiter(1, 60_000);
  const sharedDeps = deps({ limiter });

  const first = await handleRequest(request("/fapi/v1/premiumIndex"), {}, undefined, sharedDeps);
  const second = await handleRequest(request("/fapi/v1/premiumIndex"), {}, undefined, sharedDeps);

  assert.equal(first.status, 200);
  assert.equal(second.status, 429);
  assert.equal(second.headers.get("Retry-After"), "60");
  assert.deepEqual(await second.json(), { error: { code: "rate_limited" } });
});
