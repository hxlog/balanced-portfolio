-- ① 521 日更覆盖率（最新交易日 2026-11-14）
SELECT count(*) tracked, count(v.index_code) covered,
       round(100.0*count(v.index_code)/count(*),2) pct
FROM bp_index_master m LEFT JOIN bp_index_valuation_daily v
  ON v.index_code=m.index_code AND v.trade_date=DATE '2026-11-14' AND v.is_primary
WHERE m.is_active AND m.is_tracked;

-- ② 连续缺失>2交易日
WITH d AS (SELECT index_code, trade_date,
                  lag(trade_date) OVER (PARTITION BY index_code ORDER BY trade_date) prev
           FROM bp_index_valuation_daily WHERE is_primary),
     g AS (SELECT d.*, (SELECT count(*) FROM bp_trading_calendar c
                        WHERE c.market='CN' AND c.is_trading
                          AND c.cal_date>d.prev AND c.cal_date<d.trade_date) missing_days
           FROM d WHERE d.prev IS NOT NULL)
SELECT count(*) AS streak_violations FROM g WHERE missing_days>2;

-- ③ 多源差异>20% 与告警对账
WITH d AS (SELECT p.index_code, p.trade_date,
                  abs(p.pe_ttm-c.pe_ttm)/nullif(p.pe_ttm,0) rel_diff
           FROM bp_index_valuation_daily p JOIN bp_index_valuation_daily c
             ON c.index_code=p.index_code AND c.trade_date=p.trade_date
            AND c.calc_src='csindex_value' AND c.pe_ttm IS NOT NULL
           WHERE p.calc_src='pingan_index' AND p.is_primary AND p.pe_ttm IS NOT NULL),
     a AS (SELECT index_code, trade_date FROM bp_data_quality_log
           WHERE metric='pe_ttm' AND level IN ('warn','error'))
SELECT (SELECT count(*) FROM d WHERE rel_diff>0.20) diff_rows,
       (SELECT count(*) FROM d WHERE rel_diff>0.20 AND NOT EXISTS
          (SELECT 1 FROM a WHERE a.index_code=d.index_code AND a.trade_date=d.trade_date)) missing_alerts;