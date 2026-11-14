import { NextRequest, NextResponse } from "next/server";
import { revalidateTag } from "next/cache";

/**
 * 失效 /valuation 的 SSR 缓存（cacheTag "valuation"，cacheLife "hours"）。
 *
 * 由估值采集任务在落库 + 分位重算完成后用内部令牌调用（X-Internal-Token），
 * 让页面立即看到新数据，不必等 cacheLife("hours") TTL。
 * 令牌：BP_INTERNAL_REVALIDATE_TOKEN（与 crypto 路由共用）。
 */
export async function POST(request: NextRequest) {
  const expected = process.env.BP_INTERNAL_REVALIDATE_TOKEN;
  if (!expected) {
    return NextResponse.json(
      { detail: "未配置内部令牌 BP_INTERNAL_REVALIDATE_TOKEN" },
      { status: 503 },
    );
  }
  if (request.headers.get("x-internal-token") !== expected) {
    return NextResponse.json({ detail: "令牌无效" }, { status: 401 });
  }
  // 第二参数 "hours" 必须与 getCachedValuationIndices 的 cacheLife("hours") 一致。
  revalidateTag("valuation", "hours");
  return NextResponse.json({ ok: true, tag: "valuation" });
}
