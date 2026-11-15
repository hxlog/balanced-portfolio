-- 清理中证 OSS perf.xls 写入的 2021 年静态快照（每 symbol 仅 24 行，且日期过旧）
DELETE FROM bp_index_quote_daily q
WHERE q.source = 'csindex_perf'
  AND q.trade_date < DATE '2024-01-01'
  AND (
    SELECT count(*) FROM bp_index_quote_daily x
     WHERE x.symbol = q.symbol AND x.adjust = q.adjust
  ) < 100;
-- 统计
SELECT count(*) AS remaining_csindex_rows
FROM bp_index_quote_daily WHERE source = 'csindex_perf';