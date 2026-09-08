-- 41: currency 精确化 — 修正 DDL 40 对 global_index_* 的笼统 USD 标记
--
-- 背景: DDL 40 按「全球指数默认 USD」把 global_index_em/global_index_sina 下
-- 所有剩余 CNY 的资产统一标为 USD, 但其中多数外国指数并非美元计价。前端
-- builder 会直接展示币种代码, 标错会误导用户, 故按实际计价币种逐 symbol 精确化。
--
-- 修正清单(按指数注册地计价货币):
--   俄罗斯RTS=RUB; 印度孟买SENSEX/孟买SENSEX=INR; 巴西BOVESPA/巴西IBOVESPA=BRL;
--   德国DAX30/德国DAX=EUR; 法国CAC40=EUR; 荷兰AEX=EUR;
--   澳大利亚标普200/澳大利亚ASX200=AUD; 英国富时100/富时100=GBP;
--   越南胡志明/胡志明=VND; 韩国KOSPI=KRW;
--   标普中国A股大盘红利低波50指数(软删除)=CNY  ← A 股指数, 被 40 误标 USD。
-- 不动: 标普500/纳斯达克/道琼斯(USD)、日经225/日经225指数(JPY) 已正确。
-- 含 is_deleted=1 的软删除重复行, 一并修正以保持数据正确性。
--
-- 幂等: 纯 UPDATE, 按唯一键 (symbol, source) 精确圈定, 可重复执行。
-- 依赖: DDL 40 已应用(bp_index_config.currency 列已存在)。

BEGIN;

-- 卢布
UPDATE bp_index_config SET currency='RUB'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '俄罗斯RTS';

-- 印度卢比
UPDATE bp_index_config SET currency='INR'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '印度孟买SENSEX';
UPDATE bp_index_config SET currency='INR'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '孟买SENSEX';

-- 巴西雷亚尔
UPDATE bp_index_config SET currency='BRL'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '巴西BOVESPA';
UPDATE bp_index_config SET currency='BRL'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '巴西IBOVESPA';

-- 欧元
UPDATE bp_index_config SET currency='EUR'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '德国DAX30';
UPDATE bp_index_config SET currency='EUR'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '德国DAX';
UPDATE bp_index_config SET currency='EUR'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '法国CAC40';
UPDATE bp_index_config SET currency='EUR'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '荷兰AEX';

-- 澳元
UPDATE bp_index_config SET currency='AUD'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '澳大利亚标普200';
UPDATE bp_index_config SET currency='AUD'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '澳大利亚ASX200';

-- 英镑
UPDATE bp_index_config SET currency='GBP'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '英国富时100';
UPDATE bp_index_config SET currency='GBP'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '富时100';

-- 越南盾
UPDATE bp_index_config SET currency='VND'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '越南胡志明';
UPDATE bp_index_config SET currency='VND'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '胡志明';

-- 韩元
UPDATE bp_index_config SET currency='KRW'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '韩国KOSPI';

-- A 股指数回 CNY(被 DDL 40 误标 USD)
UPDATE bp_index_config SET currency='CNY'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '标普中国A股大盘红利低波50指数';

COMMIT;

-- 验证: global_index 系全部计价币种
SELECT symbol, currency FROM bp_index_config WHERE source LIKE 'global_index%' ORDER BY symbol;
