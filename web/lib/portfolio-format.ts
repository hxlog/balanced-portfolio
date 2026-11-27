/**
 * /dashboard 组合元信息的纯展示格式化（可在 vitest 下单测）。
 *
 * 背景：组合下拉列表来自 `GET /api/portfolios`，该接口**不返回**
 * `result_updated_at` / `data_as_of_date`（只有单个组合详情/回测结果体才带）。
 * 因此这里按「字段可选」降级：缺失时返回 null，调用方不渲染日期，绝不报错、
 * 也不用其它字段臆造「最近更新」。
 */

export interface PortfolioUpdateFields {
  /** 结果写入时间（ISO datetime）；旧后端/列表接口可能缺失。 */
  result_updated_at?: string | null;
  /** 结果行情截至日（YYYY-MM-DD）；旧后端/列表接口可能缺失。 */
  data_as_of_date?: string | null;
}

const DATE_PREFIX = /^(\d{4})-(\d{2})-(\d{2})/;

/**
 * 组合的「最近更新」日期（YYYY-MM-DD）：优先结果更新时间，其次数据截至日。
 *
 * - 两个字段都缺失/为空 → null（调用方不显示日期）；
 * - 纯日期/带时区时间戳都只展示日期部分（不做时区换算，避免 +08:00 被推到前一天）；
 * - 无法解析的字符串 → null，不抛错、不阻塞渲染。
 */
function parseUpdatedDate(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const text = String(raw).trim();
  if (!text) return null;
  const matched = DATE_PREFIX.exec(text);
  if (matched) return matched[1] + "-" + matched[2] + "-" + matched[3];
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return null;
  const pad = (value: number) => String(value).padStart(2, "0");
  return (
    parsed.getFullYear() + "-" + pad(parsed.getMonth() + 1) + "-" + pad(parsed.getDate())
  );
}

export function formatPortfolioUpdatedDate(
  portfolio: PortfolioUpdateFields,
): string | null {
  // result_updated_at 优先；它缺失/非法时再退到 data_as_of_date（两者都可能没有）。
  return parseUpdatedDate(portfolio.result_updated_at) ?? parseUpdatedDate(portfolio.data_as_of_date);
}
