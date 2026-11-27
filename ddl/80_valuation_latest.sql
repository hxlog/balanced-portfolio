-- 80: 指数估值最新快照表（Valuation Band 快速接口）+ 中证全指 000985 主数据
--
-- 背景（需求 2 / 需求 3）：
--   首页 Valuation Band 需要「一次请求返回全部跟踪指数的 4 指标当前值/分位/近 1 年
--   sparkline/涨跌」，旧 /api/valuation/indices 的 CTE+LATERAL（每指数扫 400 天行情 +
--   最新分位）冷启动 6s 级，无法满足 <50ms。本表由估值任务收尾（run_valuation_ingest
--   最后一步）全量刷新，/api/v1/valuation/indices 只读本表 + 若干小表 JOIN。
--
-- 口径：
--   - 数值列来自 bp_index_valuation_daily 的最新 is_primary 行（calc_src 标记口径）；
--   - percentiles 存 4 指标 × 5 窗口（1y/3y/5y/10y/all）的预计算分位，供前端窗口切换
--     零查询；pe_percentile 等 4 列是 5y（主窗口）的扁平冗余，方便旧字段名消费；
--   - pe_spark 存最近 1 年的周频 sparkline：{"pe_ttm": [[date, value], ...], "pb": ...,
--     "dividend_yield_ttm": ..., "erp": ...}（列名沿用方案里的 pe_spark，实际含 4 指标）；
--   - close_price/change_pct/change_52w_pct/position_52w_pct 由刷新任务从
--     bp_index_quote_daily(bfq) 预计算，避免请求路径扫行情表；
--   - coverage_start = 该指数主口径估值序列的最早日期，用于前端标注「历史覆盖起点」
--     （如中证A500 000510 仅 2024-06 起；中证全指 000985 由中证官网 fallback 从接入日起）。
--
-- 依赖：52（bp_index_master / bp_index_valuation_series）、60（csindex_perf 行情源注册）。
BEGIN;

CREATE TABLE IF NOT EXISTS bp_index_valuation_latest (
    index_code          TEXT PRIMARY KEY
                        REFERENCES bp_index_master(index_code) ON DELETE CASCADE,
    trade_date          DATE NOT NULL,
    calc_src            TEXT NOT NULL REFERENCES bp_data_source(code),
    is_primary          BOOLEAN NOT NULL DEFAULT FALSE,
    pe_ttm              NUMERIC(14,4),
    pb                  NUMERIC(14,4),
    dividend_yield_ttm  NUMERIC(10,6),
    erp                 NUMERIC(10,6),
    pe_percentile       NUMERIC(8,4),
    pb_percentile       NUMERIC(8,4),
    dividend_percentile NUMERIC(8,4),
    erp_percentile      NUMERIC(8,4),
    percentiles         JSONB,
    pe_spark            JSONB,
    close_price         NUMERIC(20,6),
    change_pct          NUMERIC(14,6),
    change_52w_pct      NUMERIC(14,6),
    position_52w_pct    NUMERIC(10,4),
    price_trade_date    DATE,
    coverage_start      DATE,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE bp_index_valuation_latest IS
    '指数估值最新快照（每指数 1 行，由估值任务收尾全量刷新；API 只读，请求路径永不重算）';
COMMENT ON COLUMN bp_index_valuation_latest.calc_src IS
    '估值口径来源（pingan_index 主源 / csindex_value 中证官网 fallback 等）';
COMMENT ON COLUMN bp_index_valuation_latest.percentiles IS
    '4 指标 × 5 窗口预计算分位：{"pe_ttm":{"1y":..,"3y":..,"5y":..,"10y":..,"all":..},...}';
COMMENT ON COLUMN bp_index_valuation_latest.pe_spark IS
    '最近 1 年周频 sparkline（4 指标）：{"pe_ttm":[[date,value],...],"pb":[...],"dividend_yield_ttm":[...],"erp":[...]}';
COMMENT ON COLUMN bp_index_valuation_latest.coverage_start IS
    '该指数主口径估值序列最早日期（前端标注历史覆盖起点，不做插值/造数）';

CREATE INDEX IF NOT EXISTS idx_val_latest_trade_date
    ON bp_index_valuation_latest (trade_date DESC);

-- 中证全指 000985：平安估值 universe（521 只）未覆盖，由估值任务的中证官网
-- fallback（bp_ingest/valuation_ingest.py）从 csindex 官方文件补 PE/股息/ERP 与行情。
-- 主数据行先在迁移里落库，保证若 fallback 当日失败，页面仍能列出该指数并显示
-- has_valuation=false（数据建设中），而不是查不到代码。
INSERT INTO bp_index_master (
    index_code, market, wind_code, name, short_name, index_type, publisher,
    base_date, base_point, income_method, weight_method, intro,
    is_active, is_tracked
) VALUES (
    '000985', 'CSI', '000985.SH', '中证全指', '中证全指', '宽基', '中证指数有限公司',
    DATE '2004-12-31', 1000, '价格指数', '调整市值加权',
    '中证全指指数由全部 A 股中剔除 ST、*ST 及上市未满一定期限的证券后组成，反映 A 股市场整体表现。',
    TRUE, TRUE
)
ON CONFLICT (index_code) DO NOTHING;

COMMIT;
