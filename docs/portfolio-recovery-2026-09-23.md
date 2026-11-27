# 恢复 bp_portfolio 中被误删的两个组合（id 12、28）

## 结论

两个组合的**定义**已完整恢复并落库（见下节「已执行的操作」）。但它们的**回测结果**
（净值曲线、基准曲线、指标、协方差、调仓记录、归因）没有被恢复——这部分数据在
`DELETE` 时随外键级联被物理回收，堆里不存在可读的死元组，只能重算。

## 事故时间线

`track_commit_timestamp` 处于关闭状态，无法把事务号换算成墙钟时间，因此用
`pg_portfolio.xmin`（事务号单调递增）与其他表交叉定位：

| 事务号 | 事件 |
|---|---|
| 641603 | 组合 28 被 DELETE |
| 641607 | 组合 12 被 DELETE（紧随其后） |
| 648152 | 本次恢复写入 |
| 648153/648154 | 现网正在跑的事务（说明库还在活动，仍有写入） |

`bp_portfolio.updated_at` 在 2026-09-23 07:12:56Z（= 北京时间 15:12:56）被同一事务
批量写到所有组合上，与 639784 事务的批量 UPDATE 一致，可作为删除时点的旁证。

**为什么能读到**：`bp_portfolio` 至今 `vacuum_count=0`、`last_autovacuum` 为 NULL，
死元组从未被清理，pageinspect 直接读堆文件即可取回删除前的行镜像。

## 已执行的操作（全部已提交）

对生产库 `81.71.158.239:5432/postgres` 执行了 `restore.sql`，一个事务内完成：

| 表 | 行数 | 说明 |
|---|---|---|
| `bp_portfolio` | 2 | id 12、28，用 `OVERRIDING SYSTEM VALUE` 保留原 id |
| `bp_portfolio_asset` | 27 + 6 | 恢复 id、成分、象限、排序 |
| `bp_portfolio_update_state` | 2 | `last_task_id` 置 NULL（见下） |
| `bp_user_portfolio_order` | 3 | 用户 1/2 的展示排序 |

验证：逐字段比对恢复行与死者元组，30/30 列全等；成分集合与堆中元组集合完全一致；
`/api/portfolios/12`、`/api/portfolios/28` 均返回 200。

### 两处刻意的降级

- **`last_run_params` 是重建的，不是取回的**。原值被 LZ4 压缩存储，而读取路径要跨越
  PostgreSQL 的 varlena 外部指针/压缩分支，直接解包不可靠。改用重建：写入
  `repositories.canonical_params` 对「组合定义 + 成分表」计算的规范快照。该重建已用
  全部 12 个存活组合验证过——**12/12 逐字节等于库中现值**。因此恢复后 `params_stale`
  为 false，不会误报「参数已变更待重算」。
- **`last_task_id` 置 NULL**。它外键指向 `bp_task`，而被引用的任务行已随级联删除消失，
  无法还原。列为可空，下次回测会自动填入。

## 未恢复、且无法恢复的部分

`bp_backtest_nav`、`bp_backtest_benchmark`、`bp_backtest_metric`、`bp_backtest_cov`、
`bp_backtest_rebalance`、`bp_backtest_attribution` 对这 12/28 两个 id **零行**，
且逐页扫描确认堆里也没有对应死元组。原因：这些表的行是每次回测「先 DELETE 再 INSERT」
的，删除当时旧版本就被回收，留下的只有本次 DELETE 的那一批，而那批随组合一起被删。

后果与补救：

- 页面能打开，组合定义、成分表、参数都正确，但净值曲线/指标/归因区是空的。
- **不会自动重算**：`enqueue_ready_portfolios` 的判据是
  `COALESCE(last_result_trade_date, data_as_of_date) < MIN(成分 last_clean_date)`，
  恢复后两边都是 2026-09-22，因此判为「已是最新」而跳过。`data_as_of_date` 也是纯缓存，
  没有真实结果支撑。
- 需要**手动触发重算**（下面给了命令），或把 `data_as_of_date` 临时置 NULL 让巡检接手。

## 下一步（需要你决定是否执行）

```bash
# 方式一：对两个组合分别触发重算（推荐）
curl -X POST http://<host>/api/portfolios/12/recompute
curl -X POST http://<host>/api/portfolios/28/recompute

# 方式二：临时清空 data_as_of_date，让 bp-beat 的 20 分钟巡检自动排队
#（重算后该列会被回填）
UPDATE bp_portfolio SET data_as_of_date = NULL WHERE portfolio_id IN (12, 28);
```

重算会用当前行情把净值/基准/指标/归因全部重新生成，与组合定义保持一致。历史净值会
从 `effective_start_date`（12: 2023-01-03，28: 2023-07-27）重算，因此曲线是完整的，
只是 `result_version` 会推进（12: 87 → 新值，28: 51 → 新值），前端缓存会自动失效。

## 对生产库的旁路改动（需要你知悉）

1. **安装了 `pageinspect` 扩展**（`CREATE EXTENSION IF NOT EXISTS pageinspect`）。
   这是持久改动。本次取证完全依赖它；如果不想留，可以
   `DROP EXTENSION pageinspect;`，代价是后续无法再做同类堆取证。
2. **遗留了 4 张 `zz_*` 调试表**：`zz_h`(26 行)、`zz_s`(32 行)、`zz_jj`(1 行)、
   `zz_t`(1 行)，都是解码器校准时建的，内容是测试值。用
   `DROP TABLE zz_h, zz_s, zz_jj, zz_t;` 清理即可。其余 zz_* 已随手删除。

## 取证过程的关键结论（备查）

`LZ4` 压缩数据在堆里的布局：varlena 头 4 字节（`word>>2` = 总长，低 2 位 `0b10`
表示压缩），之后 8 字节（前 4 字节该数据的 `pg_column_size`，后 4 字节是 PostgreSQL
lz4 封装头），再之后才是纯 LZ4 block 流。**踩过的坑**：把压缩值当成 18 字节外部指针
跳过，会导致其后所有列错位——这是最初 id 12 解到一半就变成乱码的原因。修正后逐列全对。

`VARATT_IS_1B_E` 判定必须是 `header == 0x01`（精确等于），而不是「低 2 位为 01」；
后者会把真实数据误判为外部指针。

## 复现/审计材料

`C:\Users\Xingy\.claude\jobs\7dd195e2\tmp\`：

| 文件 | 内容 |
|---|---|
| `restore.sql` | 已执行的恢复脚本（可重复审阅） |
| `recovered.json` | 全部可恢复行的原始堆镜像 |
| `heapdecode.py` | 堆元组解码器（含 numeric/jsonb/varlena 处理） |
| `lz4block.py` | 纯 Python LZ4 block 解压 |
| `gen_restore.py` | 恢复脚本生成器（含 `canonical_params` 重建） |
| `heapsnap/` | 相关堆页的原始快照 |

解码器的可信度依据：`validate.py` 用「解码出的元组内容多重集 ⊇ 全部存活行」做校验，
所有目标表通过；numeric、lz4、`last_run_params` 三项各自有独立的对抗性验证。
