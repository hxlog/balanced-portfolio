-- =====================================================================
-- 50: 行情日期区间的可见性 —— bp_asset_data_status.first_clean_date
--     + bp_backtest_coverage(每次回测的成分覆盖判定)
--
-- 背景: 之前全库只有「最新清洗日」(last_clean_date), 没有任何「最早清洗日」。
-- 于是三处 UI 都无法回答「这个标的数据到底从哪天到哪天」:
--   - /builder 选标的时只有一个红徽章「滞后 N 日」, 新建的资产连徽章都没有
--     (is_lagging=false 走 ?? 短路), 只是被默默沉到列表最底;
--   - 变更对话框看不出本次新增的标的行情够不够;
--   - /dashboard 看不出「某标的在回测起点时根本没有数据、权重恒为 0」。
--
-- 口径: first_clean_date = 该资产在 bp_quote_clean 里的 MIN(trade_date)。
-- 与 last_clean_date 一样只在 with_count=True 的分支刷新(同一次表扫描随身取回,
-- 零额外查询), 热路径 with_count=False 不碰本列 —— 守住 COUNT 分级不变式。
--
-- bp_backtest_coverage: 「未覆盖」判定**不能**用 first_clean_date > effective_start
-- 近似 —— 引擎的真实准入条件是「标的在滚动窗口内攒够 min_window 个真实收盘日」
-- (backtest.py:available_assets), 有数据但不足 min_window 的标的同样拿不到权重。
-- 故把判定结果在回测时一次算好落库, 请求路径只读表(与本仓预计算看板同约定)。
-- coverage 与 method 无关(四种方法共用同一价格面板与同一 effective_start),
-- 故 PK 不含 method。
--
-- 幂等: ADD COLUMN IF NOT EXISTS + CREATE TABLE IF NOT EXISTS + 回填带 IS NULL 守卫。
-- =====================================================================

ALTER TABLE bp_asset_data_status
  ADD COLUMN IF NOT EXISTS first_clean_date DATE;

COMMENT ON COLUMN bp_asset_data_status.first_clean_date IS
  '该资产最早一条清洗行情日(MIN(trade_date) of bp_quote_clean); 仅在 with_count=True 的刷新分支随 MAX/COUNT 一起写入, 热路径不覆盖';

-- 回填: 一次 GROUP BY 扫完整张 hypertable(对标 ddl/40 的 row_count 回填模板)。
-- IS NULL 守卫使重复执行无副作用。
UPDATE bp_asset_data_status st
SET first_clean_date = sub.d
FROM (
    SELECT symbol, source, MIN(trade_date) AS d
    FROM bp_quote_clean
    GROUP BY symbol, source
) sub
WHERE st.symbol = sub.symbol
  AND st.source = sub.source
  AND st.first_clean_date IS NULL;

-- 每次回测的成分覆盖判定(与 method 无关, 故不含 method 维)。
CREATE TABLE IF NOT EXISTS bp_backtest_coverage (
    portfolio_id       BIGINT  NOT NULL REFERENCES bp_portfolio(portfolio_id) ON DELETE CASCADE,
    symbol             TEXT    NOT NULL,
    source             TEXT    NOT NULL,
    first_date         DATE,
    last_date          DATE,
    first_covered_date DATE,
    covered_at_start   BOOLEAN NOT NULL,
    CONSTRAINT pk_bp_backtest_coverage PRIMARY KEY (portfolio_id, symbol, source)
);

COMMENT ON COLUMN bp_backtest_coverage.first_date IS
  '成分在价格面板里的首个真实收盘日; NULL=该资产尚无清洗数据';
COMMENT ON COLUMN bp_backtest_coverage.first_covered_date IS
  '成分首次真正拿到权重的交易日(窗口内攒够 min_window 个真实收盘日的次日建仓); NULL=全区间都没拿到过';
COMMENT ON COLUMN bp_backtest_coverage.covered_at_start IS
  'first_covered_date <= 组合 effective_start, 即回测开始那天该成分已参与; false=回测结果不含它';
