# P2 · 旧行情链迁移、清洗与回测接入 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把旧指数/商品/汇率行情链迁入 `bp_etl` 统一调度（当日就绪、多源锚定、可观测），
并把 A 股/港股/ETF/基金净值接入 `bp_quote_clean` 清洗面板与回测/构建器（L3），
同时部署第二 relay 通道、停用旧 ad-hoc cron 与 1h 轮询。

**Architecture:** 复用 P1 的 `bp_etl` 框架（registry/adapters/orchestrator/quality），
新增 `legacy_index` dataset 与 EM relay 通道；迁移 77 建 `managed_by` 桥接配置；
清洗由 ETL 收尾触发（`bp_api/quant/cleaning.py` 扩展），回测/构建器走既有
`symbol@source` 体系无感接入；旧 cron 以 `BP_ETL_MODE` 开关灰度下线。

**Tech Stack:** 同 P1（Python 3.13 / psycopg3 / curl_cffi / FastAPI / Next.js / PM2 / systemd）。

**Spec:** `docs/superpowers/specs/2026-11-23-unified-market-etl-design.md`

## Global Constraints

- 继承 P1 全部 Global Constraints（bfq/hfq 口径、收盘确认、内存/并发上限、测试与提交规范）。
- 旧表/旧 API/回测语义不得回归；旧链迁移必须保留回滚开关。
- `bp_quote_clean` 口径不变：A 股日历对齐、内部线性插值、非 CNY 先按当日 `fx_sina` 折算、
  OHLC 同乘、volume 不折、无汇率日不产出、尾部护栏报错不静默截断。
- `quant/coverage.py` 是"行情未覆盖"判定唯一来源，不得在别处近似。
- 不得在服务器新增公网端口；relay2 仅监听 127.0.0.1。
- 不提交任何代理/VLESS 配置；服务器配置放 `/etc/bp-relay2/config.json`（root 600）。

## Review Focus

1. **港股清洗时区/汇率**：HKD 资产必须先折 CNY 再插值；HK 节假日与 A 股日历差异导致的
   "尾部缺口"必须由尾部护栏报错而非静默截断。
2. **旧链口径不变**：旧指数 bfq 值迁移前后必须逐日一致（抽样校验），EM relay 回退不得混入
   不同基准的复权值。
3. **回测无未来函数**：接入 v3 资产后 `test_backtest.py` 的"篡改未来收益不改变历史净值"
   约束必须仍然通过。
4. **旧 cron 下线顺序**：必须先确认 bp-etl 同 dataset 已连续 2 个交易日达标，再注释旧 cron；
   回滚脚本必须在发布前演练。
5. **桥接配置规模**：一次性 seed 9,430 个资产配置会让 admin 资产池/列表变慢或体验变差，
   必须分页/按需启用并有性能验收（`/api/assets/unified` P95 < 300ms）。

---

### Task 1: 第二 relay（prologue VLESS）部署与通道注册

**Files:**
- Create: `deploy/bp-relay2.service`（systemd unit 模板，含 `ExecStart=/usr/local/bin/bp-relay run -c /etc/bp-relay2/config.json`）
- Create: `deploy/install-relay2.sh`（幂等：写 config（从环境变量/参数，不入 git）、enable/restart、健康检查）
- Modify: `bp_etl/channels.py`（注册 `relay_prologue` 通道，读 `BP_ETL_RELAY2=http://127.0.0.1:10810`）
- Test: `bp_api/tests/test_etl_channels.py` 增补（未配置时降级 direct）

**Interfaces:**
- `ChannelSpec(name='relay_prologue', kind='http_proxy', url=..., concurrency=2, rate=1.0)`；
  `probe_channel(name) -> ChannelProbe(ok, latency_ms, egress_ip)`。
- 部署后在管理页源矩阵中可见 `relay_sg`/`relay_prologue` 健康度。

- [ ] **Step 1: 写 systemd unit 与安装脚本**（脚本不落 VLESS 参数，改为读服务器 `/etc/bp-relay2/config.json`，
  该文件由部署者写入；仓库只放 `config.example.json`，节点参数打码）。
- [ ] **Step 2: 服务器安装并验证**：`systemctl status bp-relay2` active；`curl -x http://127.0.0.1:10810 https://push2his.eastmoney.com/...` 200；
  记录 egress IP 与时延到验收报告。
- [ ] **Step 3: 通道注册 + 单测**；提交 `数据: 新增第二 relay 通道与部署脚本`。

### Task 2: `legacy_index` 数据集（521 跟踪池 + 旧商品/汇率保留）

**Files:**
- Create: `bp_etl/datasets/legacy_index.py`
- Create: `bp_etl/adapters/sina_index.py`（或复用 Task 5 sina adapter 扩展指数函数）
- Test: `bp_api/tests/test_etl_legacy_index.py`

**Interfaces:**
- `universe(conn) -> list[str]`：`bp_index_master` where `is_active and is_tracked`（521）；
  商品/国债/汇率沿用 `bp_index_config` 现有 source（`cmdty_main_sina`/`bond_csi_treasury`/`fx_sina`）。
- 源路由（按 `bp_index_config.source`/代码段）：A 股宽基（000/399/899）→ 新浪/腾讯直连；
  CSI 定制（930/931/932/H30/980）→ `eastmoney:relay_sg`（失败切 `relay_prologue`）；
  全球指数 → EM relay；港股指数 → EM relay；商品/国债/汇率 → 现有直连源。
- 质量门沿用 P1；额外校验：当日写入的 bfq 与前一交易日 ratio 在 0.5–1.5 之外记 issue。

- [ ] **Step 1: 测试**：按代码段路由到正确 adapter/通道；EM direct 被禁时自动走 relay；
  A 股指数走新浪/腾讯不走 relay；521 只 universe 数量断言。
- [ ] **Step 2~4: 红→实现→绿→提交** `数据: 新增旧指数链统一 dataset`。

### Task 3: 旧链自愈任务迁入（重试/看护/补洞）

**Files:**
- Modify: `bp_etl/datasets/legacy_index.py`（`repair()`/`watch()` 计划任务）
- Create: `bp_etl/jobs.py`（dataset=`legacy_index` 的 retry/watch 波次计划）
- Test: `bp_api/tests/test_etl_legacy_jobs.py`

**Interfaces:**
- `plan_retry(now) -> WavePlan`（每 2 小时重试缺失标的，单次预算 20 分钟）；
  `plan_watch(now) -> WavePlan`（每工作日 17:10 刷新 `bp_index_quote_health` + 极值表）。
- 复用 `bp_api/repositories_valuation.upsert_quote_health` 写健康表。

- [ ] **Step 1: 测试**：缺失清单生成正确（lag>0）；预算耗尽提前停止并记录；health 写入幂等。
- [ ] **Step 2~4: 红→实现→绿→提交** `数据: 旧链重试与看护迁入 bp_etl`。

### Task 4: 旧调度下线（灰度 + 回滚）

**Files:**
- Create: `scripts/etl_legacy_cron_toggle.sh`（备份/注释/恢复 root crontab 与 `/etc/cron.d/bp-*` 行情条目）
- Modify: `deploy/ecosystem.config.cjs`（`bp-ingest` 环境变量 `BP_INGEST_MODE=cleaning-only` 或停用）
- Modify: `deploy/OPS.md`、`docs/data/asset-pool-etl.md`
- Test: 演练脚本在测试服务器/临时环境（或在生产先 `--dry-run` 输出 diff）

**Interfaces:**
- 脚本模式：`toggle.sh dry-run|disable|restore`；disable 生成备份 `/opt/backup/crontab-<ts>` 与
  `/etc/cron.d/bp-*.bak`；restore 完全回滚。停用范围：v3 五条 + `bp-index-quotes`/
  `bp-index-quotes-retry`/`bp-xueqiu-quotes`/`bp-csindex-quotes`/`bp-quote-repair` 的行情部分
  （crypto/MVI/估值/基金风险等保留）。

- [ ] **Step 1: 写脚本并 dry-run 输出 diff**（不改系统）。
- [ ] **Step 2: 连续 2 个交易日 bp-etl 各 dataset 达标后执行 disable；记录 PM2/cron 状态到验收报告。**
- [ ] **Step 3: 演练 restore；提交** `数据: 旧行情 cron 灰度下线与回滚脚本`。

### Task 5: 迁移 77 + 清洗层接入 v3 资产

**Files:**
- Create: `ddl/77_etl_asset_bridge.sql`
- Modify: `bp_api/quant/cleaning.py`（新增 v3 资产读取/写入路径；保持现有函数语义）
- Modify: `bp_etl/orchestrator.py`（dataset 达标后触发 `rebuild_clean(symbols=...)`）
- Create: `bp_api/tests/test_etl_cleaning_bridge.py`

**Interfaces:**
- `bp_index_config.managed_by`（NULL 旧链、'bp_etl' 新链）+ 桥接配置 seed 规则：
  仅 `is_selectable=TRUE` 的 v3 资产（A 股全量、ETF 全量、港股按产品决定），`adjust='hfq'`，
  `currency='CNY'(A/ETF)/'HKD'(HK)`，`source='etl_a_stock'/'etl_etf'/'etl_hk_stock'`（新
  `bp_data_source` 码，逻辑源）。cleaning 从 `bp_stock_quote_daily`/`bp_etf_quote_daily`
  按锚定源读取（含 bfq 用于展示），写 `bp_quote_clean`（hfq 用于回测口径）。
- `rebuild_clean` 调用方式不变，只扩大 symbols 来源；`refresh_asset_status` 计数字段兼容。

- [ ] **Step 1: 测试**：桥接配置生成数量正确；港股清洗走 fx_sina 折算；缺失汇率日不产出行且
  记 `MissingFxRate`；插值/尾部护栏用例保持既有测试全绿；`bp_quote_clean` 中 v3 资产行可查。
- [ ] **Step 2~4: 红→实现→迁移临时库→绿→提交** `数据: 迁移 77 桥接配置并将 v3 资产接入清洗面板`。

### Task 6: 回测/构建器接入与无未来函数回归

**Files:**
- Modify: `bp_api/repositories.py`（`list_assets` 支持 `managed_by='bp_etl'`；`load_price_panel`
  按新 source 读取 `bp_quote_clean`，保持返回结构）
- Modify: `bp_api/repositories_valuation.py`（如覆盖/区间展示读取新资产）
- Create/modify: `bp_api/tests/test_etl_backtest_bridge.py`
- Modify: `web/lib/api.ts`（如资产类型/复权选项需同步）

**Interfaces:**
- 资产 key：`{symbol}@etl_a_stock` 等；`list_assets` 返回的 `adjust_modes` 只含 bfq/hfq；
  `load_price_panel(assets, ..., adjust='hfq')` 对 v3 资产返回清洗序列。
- 覆盖判据：`quant/coverage.py` 不变（v3 资产按同一逻辑计算 effective_start/covered_at_start）。

- [ ] **Step 1: 测试**：v3 资产能进 `run_backtest` 且无异常；`test_backtest.py` 无未来函数断言
  在含 v3 资产的用例上通过；覆盖判定与 `_coverage_rows` 一致；`/api/assets/unified` 仍正常。
- [ ] **Step 2~4: 红→实现→绿→提交** `数据: 回测/构建器接入 ETL 管理资产`。

### Task 7: 端到端验收（当日全链路）+ 运维文档

**Files:**
- Create: `scripts/etl_e2e_acceptance.py`（读取 run/coverage/clean 并断言当日全绿）
- Create: `docs/superpowers/reports/2026-11-2x-etl-e2e-acceptance.md`
- Modify: `docs/data-sources.md`（源矩阵与通道）、`deploy/OPS.md`（bp-etl 运维/重放/回滚）

**Interfaces:**
- 验收脚本输出：每 dataset 的 `last_date`/覆盖率/就绪时间/源使用；清洗面板当日覆盖；
  回测抽样可跑；`/admin/market-data` API 200。
- 全量测试：`python -m pytest bp_api/tests -q` + web `typecheck/test/build`。

- [ ] **Step 1: 写验收脚本（只读）**。
- [ ] **Step 2: 连续 2 个交易日收盘后执行并留档报告**。
- [ ] **Step 3: 文档 + 提交** `文档: 行情 ETL 端到端验收与运维手册`。

### Task 8（可选）: 源扩展研究（新浪 ETF hfq 因子 / 雪球指数）

**Files:**
- Create: `docs/superpowers/reports/2026-11-2x-source-expansion-research.md`

**Interfaces:** 研究结论（是否可作 ETF hfq 第二锚 / 旧指数备用源），含端点、口径、限速实测；
若可行，单独立项接入。

- [ ] **Step 1: 实测新浪 ETF hfq 因子端点与当日可用性、雪球指数接口可用性**，写结论。
- [ ] **Step 2: 提交** `文档: 行情源扩展研究报告`。

---

## 并行开发拆分（multi-agent，写入范围互斥）

| 工作流 | 任务 | 写入范围 |
|---|---|---|
| A 框架核心 | P1-2、3、7、8、9 | `bp_etl/{config,registry,channels,rate_limit,retry,anchors,writer,coverage,quality,health,orchestrator}.py` |
| B 适配器 | P1-4、5、6 + P2-2（adapter 部分） | `bp_etl/adapters/**`、`bp_etl/datasets/legacy_index.py` |
| C 数据集/重建 | P1-10、11 | `bp_etl/datasets/{a_stock,hk_stock,etf,fund_nav}.py`、`bp_etl/cli.py`、`bp_etl/rebuild.py` |
| D API/前端 | P1-12、13 | `bp_api/data_health.py`、`bp_api/main.py`、`web/app/admin/market-data/**`、`web/components/admin/**`、`web/lib/api.ts` |
| E 基础设施 | P1-1、14 + P2-1、4 | `ddl/75*、76*`、`deploy/**`、`scripts/etl_*` |
| F 清洗/回测 | P2-5、6、7 | `ddl/77*`、`bp_api/quant/cleaning.py`、`bp_api/repositories*.py`、`bp_api/tests/test_etl_*` |

依赖顺序：E(1) → A(2/3) → B(4/5/6) ∥ C 依赖 A/B 接口 → D 依赖 A 的表与 schemas →
F 依赖 P1 达标 + C；P2-1/4 独立可与 A 并行。每个 workstream 完成后由独立 reviewer 跑
`pytest` + 针对 Review Focus 的检查再合入。
