# 全站整改 · 部署与验收报告（2026-11-27 22:15）

## 部署
- 生产：81.71.158.239，git 最新 `b67d571`（含 57cb61b 修复），干净 `.next` 重建（构建 exit 0）。
- PM2：bp-api / bp-web / bp-worker / bp-beat / bp-etl online；bp-ingest 保持停用（旧调度器退役）。
- 迁移：ddl/78（basket is_demo）、79（data_freshness + hk_index_tx）、80（valuation_latest + 000985 master）已应用。
- 新增/恢复 cron：bp-cffex（15:30/40/50 + 16-23 每10min + 02:00）、bp-valuation（21-23 每15min + 09:00）、bp-mvi（23:50/09:20）。

## 功能验证（生产）
- 新增匿名 API 全部 200：`/api/v1/market/data-freshness`（8 类）、`/api/v1/valuation/indices`（521 指数快照）、`/api/v1/market/mvi`（11-27，232 周频点）、`/api/v1/market/mvi/overlay`（参数校验）。
- `/api/baskets` 匿名可读示例篮子「A股核心资产 12 只」（id=4，12 成分，etl_a_stock）。
- HSI 详情：跟踪误差口径修复后 SH513660 **4.82%**、SH513600 4.74%、SZ159920 4.61%（原 50.57%）；tracker 返回数据截至/更新时间字段。
- MVI 修复：as_of 11-27，mvi 31.54，周频去周末点、NaN 不再置 0 分位。
- 浏览器（Chrome headless，生产 URL）页面无 JS 报错：/valuation、/valuation/HSI、/dashboard、/dashboard?mode=basket、/cffex、/crypto、/otc-derivatives-pricing 全部 0 错误；**首页仍有 2 个 console 错误（HierarchyRequestError/#418，视觉未受影响，待修）**。

## 数据审计（2026-11-20 ~ 11-27）
| 数据 | 最新 | 状态 |
|---|---|---|
| A股（bfq/hfq） | 11-27（7915/5217） | ✅ 每日连续 |
| ETF（bfq/hfq） | 11-27（1353/1352） | ✅ |
| 港股 bfq/hfq | 11-27 / 11-27 | ✅（hfq 已追平） |
| 基金净值 | 11-27 | ✅ |
| 指数行情 distinct | 11-27 493（11-20 675） | ⚠️ 仍低于历史覆盖，靠新免费源脚本继续补 |
| 指数估值 | 11-27（521） | ✅ |
| MVI | 11-27 | ✅ |
| 股期 contract/premium | 11-27 / 11-27 | ✅ |
| bp_quote_clean | 11-27 | ✅ |
| legacy_index state | bfq 11-27 / hfq 11-24 | ⚠️ hfq 缺口 |
| 全市场估值快照 | 11-14 | ⚠️ 东财 clist 封禁，待新免费源 |

## 代码审查与修复
- 后端 P0/P1 修复：backlog 默认不再超期丢弃；freshness 派生查询改用 SAVEPOINT；market valuation 收盘前不写库；DB 集成测试改为显式 BP_MIG_TEST_DSN（不再读生产口令/硬编码 IP/无 WHERE 清表）；compute_mvi 空数据保护；MVI 路由参数名 bug；中证 fallback Decimal→float。
- 前端 P1/P2 修复：详情页切换指标旧数据错标；窗口切换失败回滚；basket 资产池重试映射；freshness a11y/超时/无数据文案；ROE×PE 对数回归线；TE/规模口径统一；根因级 PPR streaming 问题通过“干净 .next 重建 + 首页/HomeCryptoSection 回滚 + Dashboard 关闭 PPR 流式壳/ModeGate searchParams 竞态”解决（除首页残留 console 错误）。
- 测试：后端 785 passed / 47 skipped；前端 typecheck 0、vitest 212 passed、build 0。

## 未完成 / 风险
1. **首页 2 个 console 错误**（HierarchyRequestError/#418）：已知，非视觉故障；需继续定位（可能仍需回滚 Navbar/root loading 或进一步简化首页 Suspense）。
2. **000985 中证全指**：估值 fallback 修复已提交 c8361c2 并在生产重跑，但截至最后一次探测仍未出现在快照/详情（需确认部署与 fallback 结果；上一条 SSH 复核被临时限流）。
3. **legacy_index hfq 11-24 缺口**（bfq 已 11-27）。
4. **指数行情覆盖 493**，低于 11-20 的 675，需要 index_quotes_free 继续跑/调度观察。
5. **全市场估值快照仍 11-14**（源封禁），已按计划降级，需要替代源。
6. **安全**：审计发现历史文档中曾提交生产库明文密码（已从当前文件移除）；**必须轮换数据库密码并清理 git 历史**（本次未执行，需用户操作/授权）。
7. 未完成：登录态/管理员页面的浏览器 E2E（无 TOTP 凭据），仅匿名与公开 API 验收；移动端截图抽样。
