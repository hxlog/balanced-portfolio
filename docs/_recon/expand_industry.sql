-- 行业分类扩面：对未分类的行业/主题指数，用最新成分权重里占比最高的申万一级行业补齐
-- 条件：排名第一的行业权重 ≥ 40% 才认定，避免一个成分分散的指数被误分类
WITH latest AS (
    SELECT index_code, max(effective_date) AS d
    FROM bp_index_constituent GROUP BY index_code
), weights AS (
    SELECT c.index_code, s.industry_l1, sum(c.weight) AS w
    FROM bp_index_constituent c
    JOIN latest l ON l.index_code = c.index_code AND l.d = c.effective_date
    JOIN bp_stock_master s ON s.stock_code = c.stock_code
    WHERE s.industry_l1 IS NOT NULL AND c.weight IS NOT NULL
    GROUP BY 1, 2
), ranked AS (
    SELECT index_code, industry_l1, w,
           row_number() OVER (PARTITION BY index_code ORDER BY w DESC) AS rn,
           sum(w) OVER (PARTITION BY index_code) AS total
    FROM weights
)
UPDATE bp_index_master m
   SET industry = r.industry_l1, updated_at = now()
  FROM ranked r
 WHERE m.index_code = r.index_code
   AND r.rn = 1
   AND m.industry IS NULL
   AND m.index_type IN ('行业', '主题')
   AND r.w / NULLIF(r.total, 0) >= 0.4;

SELECT index_type, count(*) total, count(industry) with_industry
FROM bp_index_master WHERE is_active AND is_tracked GROUP BY 1 ORDER BY 2 DESC;