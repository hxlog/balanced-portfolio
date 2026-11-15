-- 只删「仅由 OSS 快照写入、行数很少」的符号上的 csindex_perf 旧行（快速版）
WITH tiny AS (
    SELECT symbol
    FROM bp_index_quote_daily
    WHERE source = 'csindex_perf'
    GROUP BY symbol
    HAVING count(*) < 100
)
DELETE FROM bp_index_quote_daily q
USING tiny
WHERE q.symbol = tiny.symbol
  AND q.source = 'csindex_perf'
  AND q.trade_date < DATE '2024-01-01';
SELECT count(*) AS remaining_csindex_rows FROM bp_index_quote_daily WHERE source = 'csindex_perf';