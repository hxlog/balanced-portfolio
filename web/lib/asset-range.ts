/**
 * 资产行情日期区间的格式化与风险标记 —— /builder、变更对话框、/dashboard 三处共用。
 *
 * 三处的「风险」含义不同, 但都用同一套判据函数, 避免各写一份后互相漂移:
 *
 *   - lagging   该资产相对平台最新清洗日落后 >= 2 个交易日(数据陈旧, 但不影响回测真实性
 *               到「少算最近几天」的程度)。只有 /builder 与变更对话框能判 —— 它们手上有
 *               is_lagging。「/dashboard 判不出来也不该判」: 组合回测只跑到全体成分都
 *               齐全的那天(load_price_panel 尾部截断), 结果页天然不存在「滞后」。
 *   - uncovered 该资产在回测起点时还没拿到权重 —— 引擎的准入条件是「滚动窗口内攒够
 *               min_window 个真实收盘日」, 不是「有没有数据」。所以这个判定**只能由后端
 *               算**(compute_coverage), 前端拿 covered_at_start 布尔值, 绝不自行用
 *               first_date > effective_start 近似(那会漏报「有数据但没攒够窗口」的一类)。
 *   - nodata    该资产连一行清洗行情都没有(新加标的/被限频卡住) —— 沉底且不参与回测。
 *   - none      正常, 无风险。
 *
 * 优先序: nodata > lagging > uncovered > none。前两者让「这个标的现在能不能用」一目了然,
 * 比「回测够不够真实」更紧急; 且无数据时 uncovered 必然是 false, 不冲突。
 */

export type RangeTone = "lagging" | "uncovered" | "nodata" | "none";

export type RangeInput = {
  /** 首个清洗日(ISO yyyy-MM-dd); 缺省/null 表示未知 */
  firstDate?: string | null;
  /** 末个清洗日(ISO yyyy-MM-dd) */
  lastDate?: string | null;
  /** 落后 >= 2 个交易日; undefined = 该调用点拿不到此信息(不判滞后) */
  isLagging?: boolean;
  /** 回测起点是否已覆盖该标的; undefined = 该调用点拿不到此信息(不判未覆盖) */
  coveredAtStart?: boolean | null;
};

/**
 * 是否「无行情数据」。
 *
 * 判据用 lastDate 而非 firstDate: 只要末个清洗日为空就说明它现在拿不出价格(既有语义与
 * builder 的沉底排序 `!a.last_clean_date` 一致)。反过来只要 lastDate 有值, 即便
 * firstDate 因旧后端缺失(该列 50 号才加, 老行可能为 NULL)也仍算有数据 —— 此时日期列
 * 降级为只显示截止日, 不能误报「暂无行情数据」。
 */
export function hasNoData(lastDate?: string | null): boolean {
  return !lastDate;
}

export function rangeTone(input: RangeInput): RangeTone {
  if (hasNoData(input.lastDate)) return "nodata";
  if (input.isLagging === true) return "lagging";
  if (input.coveredAtStart === false) return "uncovered";
  return "none";
}

/** 风险色调 → Tailwind 语义色 class。none 为中性灰。 */
export const RANGE_TONE_CLASS: Record<RangeTone, string> = {
  lagging: "text-destructive",
  uncovered: "text-warning",
  nodata: "text-muted-foreground",
  none: "text-muted-foreground",
};

/** 无数据时的占位文案(与 builder 既有「待拉取」口气一致)。 */
export const NO_DATA_LABEL = "暂无行情数据";

const ISO_RE = /^(\d{4})-(\d{2})-(\d{2})/;

/**
 * 中文日期: `2020-01-04` → `2020年1月4日`(月/日不补零, 与用户给的示例一致)。
 * 无法解析的输入(空串/异常格式)返回 null, 由调用方决定降级文案。
 */
export function formatDateCN(iso?: string | null): string | null {
  if (!iso) return null;
  const m = ISO_RE.exec(iso);
  if (!m) return null;
  return `${m[1]}年${Number(m[2])}月${Number(m[3])}日`;
}

/**
 * 区间文案: `2020年1月4日 - 2026年9月25日`。
 *
 * 降级: 只有截止日 → 只显示截止日(老库 first_clean_date 为 NULL, 见 hasNoData 注释);
 * 只有起始日 → 只显示起始日; 两者皆无 → null(调用方显示 NO_DATA_LABEL)。
 */
export function formatRangeCN(first?: string | null, last?: string | null): string | null {
  const f = formatDateCN(first);
  const l = formatDateCN(last);
  if (f && l) return `${f} - ${l}`;
  return l ?? f ?? null;
}
