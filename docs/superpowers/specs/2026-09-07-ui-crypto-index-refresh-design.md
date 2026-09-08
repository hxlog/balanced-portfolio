# 设计文档：UI 打磨 + Crypto 数据源修复 + 非CNY限制 + 索引优化 + Diff 重构

日期：2026-09-07 · 状态：已与用户逐项确认（10 问全部有答案）

## 背景

九项需求的根因分析已由 4 个并行探索完成并经人工复核。用户确认以 max effort 执行，允许直连生产 DB（Tailscale 100.75.138.35）做索引/表结构优化，最终验收标准 = 前端模拟用户正常使用可访问、数据正确。

## 已确认的决策

| # | 决策 |
|---|---|
| 1 | BTC 源：**yfinance 现货主源 + 新浪 CME 期货 fallback 链**（`ak.futures_foreign_hist("BTC")`，镜像 `gold_comex_em` 模式，经 `AGGREGATE_CHAINS` ratio re-anchor） |
| 2 | 非 CNY 限制口径：**只限外币计价指数**（日经225指数、标普500指数、纳斯达克指数、HSI 等港币计价也算）；QDII ETF（人民币场内价）不限制 |
| 3 | 勾选非 CNY 资产时弹一次 **AlertDialog** 确认；builder 主界面无常驻警示条；纯前端软限制 |
| 4 | 确认变更对话框：**只显示有变更的行**；资产构成用分组表格逐项渲染（新增/移除/调整三组），废弃整段字符串流 |
| 5 | `COUNT(*)` 热点改为 ingest 增量维护 `bp_asset_data_status.row_count`（DDL 加列 + 首次全量回填） |
| 6 | 全站容器宽度按最佳实践统一到 **1440px**（design-system 既定值）；首页 hero 5xl 窄版式保留 |
| 7 | /cffex 涨跌幅 = Section 1 指数卡片右下角（数字+箭头），**仅手机端**左移 1px |
| 8 | OTC 标题统一为 **「场外衍生品定价 · Experiment」**（metadata/H1/Navbar/首页 CTA 全部同步） |
| 9 | UI refresh = token 级最细打磨（OpenAI/Next.js 现代扁平风），**保持现有颜色方案与 UI 标准统一** |
| 10 | BTC fallback 切换后需**回填 CME 期货历史 + 重算 crypto 相关性矩阵** |

## 一、Crypto 数据源 + /admin/assets 修复

### 1.1 新增 `btc_cme_sina` source（bp_ingest/sources.py）

- `_fetch_btc_cme_sina(symbol, start, end, extra)`：调 `ak.futures_foreign_hist(symbol="BTC")`，归一化标准列 schema，`_finalize`。镜像 `_fetch_gold_comex_em`（sources.py:624-634）。
- `SOURCES` 注册 + `AGGREGATE_CHAINS` 加 `crypto_yfinance: [btc_cme_sina]` 链 → Yahoo 429/连接错误时自动降级，fallback 帧经 `_align_fallback_to_base` 重叠收盘比率 re-anchor。
- DDL：`bp_data_source` 插入 `btc_cme_sina` 行（vendor 新浪, logical_source crypto, is_backup=TRUE）。

### 1.2 probe 端点透传 extra（bp_api/main.py:661-708）

- `POST /api/admin/assets/probe` 接收表单的 `extra_params`（adjust/indicator），传给 `fetch_with_fallback`，替代现在的空 `{}` → 测试成功 == 该参数组合真能拉数。
- 前端 `web/app/admin/assets/page.tsx` probe 调用带上当前表单的 adjust/category 派生 extra。

### 1.3 futures_cffex 不可添加

- `bp_data_source` 该行标记（新增 `is_addable` 或复用现有字段过滤），前端下拉排除；CFFEX 走独立 pipeline 的说明保留。

### 1.4 历史回填 + 重算

- 拉取 CME BTC 期货全量历史入 `bp_index_quote_daily`（`BTC-USD@crypto_yfinance` 主键不变？——**注意**：fallback 数据落主 source 行，re-anchor 后与现货收益对齐；具体落库 key 遵循 `fetch_with_fallback` 现有聚合语义）。
- 重跑 `crypto_corr.compute_and_store` 刷新 3 张 crypto 表 + revalidate 前端缓存。

### 1.5 端到端验收

对每类 source（cn_index_em / etf_em(hfq,qfq) / bond_csi_treasury / cmdty_main_sina / hk_index_em / global_index_em / crypto_yfinance+btc_cme_sina / dxy_em / gold_comex_em）模拟用户操作：probe → 保存 → sync，全部成功且数据入库。

## 二、非 CNY 资产限制（builder）

- **DDL**：`bp_index_config` 加 `currency TEXT NOT NULL DEFAULT 'CNY'`；seed 更新：`global_index_em/sina` 全部资产标对应外币（JPY/USD），`hk_index_em/sina` 标 HKD；QDII ETF（etf_em 的 513xxx/159xxx）保持 CNY。
- **API**：`/api/assets` 与 `/api/admin/assets` 透出 `currency`；`web/lib/api.ts` Asset 接口加字段。
- **AssetPicker**：rank 函数加一档——`currency !== 'CNY'` 排最后（在 stale 沉底之后/之前需定序：非CNY 且 stale 最末）；列表项显示币种小标签。
- **AlertDialog**：勾选非 CNY 资产时弹确认——文案说明「该资产以外币计价，当前无外汇数据换算，回测收益未包含汇率变动，可能影响回测效果」，确认后才加入。

## 三、数据库索引 + row_count

- **DDL**（与 currency 同一迁移或分两个编号）：
  - `bp_asset_data_status` 加 `row_count BIGINT`；首次全量回填（每资产 COUNT 一次）；`refresh_asset_status` 改为读维护值，ingest upsert 后增量更新（本次写入新增行数 delta 或周期性校准）。
  - `CREATE INDEX idx_bp_portfolio_demo_order ON bp_portfolio (display_order, portfolio_id) WHERE is_demo = TRUE;`
  - `CREATE INDEX idx_cffex_premium_variety_type_date ON bp_cffex_premium_daily (variety, contract_type, trade_date);`
- 生产库（100.75.138.35）直接应用 + `ANALYZE`；用 `EXPLAIN` 验证热点查询走新索引。
- 其余查询探索已确认被现有 PK/索引精确覆盖，不加冗余索引。

## 四、确认变更对话框重构（web/components/ChangeDiffDialog.tsx + BuilderClient.tsx）

- **diff key 改 placement 级**：`symbol@source@quadrant`，修复同资产多象限产生 N-1 条假「调整」的 bug。
- **输出分组**：`added`（资产×象限）、`removed`、`moved`（同 symbol@source 象限变化，显示 旧→新）三组，每组表格/列表逐项渲染，一行一项。
- **只显示变更行**：无变更的参数不出现在 diff 表。
- **容器**：`sm:max-w-lg` → `sm:max-w-3xl`；`max-h-[45vh]` → `max-h-[60vh]`；资产构成区块独立于参数表，占满宽度。

## 五、UI 打磨（token 级，OpenAI/Next.js 现代扁平）

### 5.1 card.tsx pt-0 bug（builder 象限卡片根因）

- `CardContent`/`CardFooter` 基类去掉全局 `pt-0 sm:pt-0`，改 `p-5 sm:p-6`；审计全站 `CardHeader+CardContent` 组合，依赖 pt-0 的用法在调用处显式补 `pt-0`（或 CardHeader 加 pb 调整），确保无双重间距回归。
- builder 象限卡片：badge 区 `min-h` + 空态 `flex-1 items-center justify-center` 垂直居中。

### 5.2 宽度统一

- navbar/footer/各页容器统一 `max-w-[1440px]`（dashboard 现值）；首页 hero 5xl 保留。
- navbar 桌面链接 `whitespace-nowrap shrink-0`，中等宽度压缩 gap，必要时 nav 区横向滚动；禁止换行。
- `docs/design-system.md` 容器规范同步更新。

### 5.3 /cffex 移动端

- TabsList：`grid-cols-3` → 横向滚动 `flex overflow-x-auto`（5 周期不折行）。
- 分位表：单元格 padding `p-4`→移动端 `px-2`；分位条 `w-12` 手机隐藏只留百分比；品种列 `sticky left-0 bg-card`；重排 `hidden md:/lg:` 断点使平板（768-1023）不横滚。
- 涨跌幅（Section 1 卡片右下角）：`max-sm` 下左移 1px（`-mr-px` 或 `translate-x-[-1px]` 级别微调）。

### 5.4 OTC 标题

- 6 处「场外衍生品定价」→「场外衍生品定价 · Experiment」（metadata title/OG、H1、Navbar、首页 CTA、methodology.mdx 描述酌情）。

### 5.5 全站扁平化 token 打磨

- 阴影规范化：卡片 `shadow-sm` → 更弱/去阴影靠 border（flat）；hover 态统一。
- 圆角/间距/标题字重 letter-spacing 统一（对照 OpenAI/Next.js 官网：更克制的阴影、更细的边框、更大的留白、更紧的标题）。
- 字体：引入 Geist（Latin，next/font）作 `font-sans` 西文栈，中文回落系统栈——保持现有排版比例。
- 颜色方案（sky 主色/涨跌语义/四象限色/chart-theme.ts）**全部不动**。
- 验收：375/768/1440 × light/dark 三视口截图，无裁切、无意外横滚。

## 六、执行与验收

- 顺序：P0（diff bug → crypto → 非CNY → cffex移动）→ P1（卡片 → 宽度/navbar → OTC标题）→ P2（索引/row_count → 全站打磨）。
- 每阶段：`python -m pytest bp_api/tests -q` + `cd web && npm run build && npm run typecheck`。
- 终验：chrome-devtools/playwright 模拟用户——登录、/admin/assets 各源 probe+添加+sync、/builder 勾选非CNY弹确认+保存 diff 正确渲染、/crypto 数据新鲜、/cffex 手机端正常。
- 改动直接落主 checkout，**不 commit**（git 由用户自己操作）；DDL 新编号迁移 + schema.sql 同步合并。
