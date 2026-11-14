# 指数估值系统 · 侦察与决策待办（Round 1）

## 侦察产出的文件
- `docs/index-valuation/01-recon-and-data-dictionary.md` —— 现有系统数据盘点 + 平安 11 个接口 + 119 个字段字典 + etf.run 模块清单 + 8 项缺口
- `docs/_recon/frontend-backend-recon.md` —— 前后端架构、路由/鉴权/预计算/缓存模式、5 个需求的「新建/修改文件清单+行号」
- `docs/_recon/db-ingest-recon.md` —— 30 张表数据字典、ingest 扩展点、调度
- `docs/_recon/shots/etfrun-*.png` —— etf.run 首页与详情页截图
- `docs/_recon/pingan-vault.json` / `reqs/` —— 平安接口原始响应（可复现）

## 已实测确认的事实（用于决策）
1. 平安 vault 接口**纯 requests 匿名可调**，每日 10~20 请求即可拉全 521 个指数（含 5 年周频 PE/PB/股息率序列、ROE/ROA 序列、前 30 大成分股权重、跟踪 ETF/联接基金、十年国债全历史）。
2. akshare 1.18.64 **没有** `index_value_hist_funddb`；`stock_zh_index_value_csindex` 走中证 OSS 的 indicator.xls，**只滚动 20 个交易日**（可日积月累）；`stock_zh_a_hist(adjust=hfq)` 可用；`stock_index_pe_lg` 是月频。
3. 现有行情主键 `(symbol, source, trade_date)` **无 adjust 维度** → 三复权必须换存储形态。
4. 现有资产池只有 63 个 A 股指数，而目标页有 521 个 → 估值必须是**独立数据域**。
