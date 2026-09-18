# 生产运维速查

适用环境：Linux、PM2、Nginx、Redis、PostgreSQL/TimescaleDB。

示例约定：

```text
应用目录  /opt/balanced-portfolio
站点域名  <your-domain>
数据库    <database-host>
```

首次安装和完整配置见 [部署说明](../docs/deployment.md)。

## 日常发版

```bash
cd /opt/balanced-portfolio
bash deploy/deploy.sh
```

脚本执行 `git pull --ff-only`、依赖安装、前端构建、PM2 重载和健康检查。它不会执行数据库迁移。

发版后检查：

```bash
pm2 status
curl -fsS http://127.0.0.1:8000/api/health
curl -s -o /dev/null -w "%{http_code}\n" \
  http://127.0.0.1:3000/api/session
sudo nginx -t
redis-cli ping
```

未登录的 Session 请求可以返回 `401`，但不能返回 `404`。

## 进程与日志

```bash
pm2 status
pm2 describe bp-api
pm2 describe bp-web
pm2 describe bp-ingest
pm2 describe bp-worker
pm2 describe bp-beat

pm2 logs bp-api --lines 100 --nostream
pm2 logs bp-web --lines 100 --nostream
pm2 logs bp-ingest --lines 100 --nostream
pm2 logs bp-worker --lines 100 --nostream
pm2 logs bp-beat --lines 100 --nostream
```

重载全部进程和环境变量：

```bash
cd /opt/balanced-portfolio
pm2 reload deploy/ecosystem.config.cjs --update-env
pm2 save
```

只重启单个进程：

```bash
pm2 restart bp-api
pm2 restart bp-web
pm2 restart bp-ingest
pm2 restart bp-worker
pm2 restart bp-beat
```

## 行情维护

在项目根目录加载虚拟环境和配置：

```bash
cd /opt/balanced-portfolio
source .venv/bin/activate
set -a
source .env
set +a
```

常用命令：

```bash
python -m bp_ingest ping
python -m bp_ingest run
python -m bp_ingest run --symbols 000300 HSI
python -m bp_ingest run --no-clean
python -m bp_ingest clean
```

`bp-ingest` 负责定期拉取常规行情和 CFFEX 日行情，并刷新清洗表。上游连续报连接错误或 `429` 时，应降低抓取频率、增加随机间隔并等待限流窗口结束；不要把浏览器 Cookie、token 或完整请求头写入仓库和日志。

需要调整抓取节奏时，在 `.env` 修改：

```env
BP_REQUEST_INTERVAL=5
BP_REQUEST_JITTER=10
BP_MAX_RETRIES=3
BP_HTTP_RETRY=4
```

修改后执行：

```bash
pm2 restart bp-ingest --update-env
```

## Celery 与 Redis

```bash
redis-cli ping
redis-cli info memory
pm2 status bp-worker bp-beat
pm2 logs bp-worker --lines 100 --nostream
pm2 logs bp-beat --lines 100 --nostream
```

生产环境应设置 `BP_TASK_MODE=celery`。`bp-worker` 执行组合回测、OTC 定价等任务；`bp-beat` 定期检查可以推进到最新行情日的组合。

弱配置服务器可先降低并发：

```env
BP_CELERY_CONCURRENCY=1
BP_BACKTEST_METHOD_WORKERS=1
```

队列持续堆积时依次检查：

1. Redis 是否返回 `PONG`。
2. `bp-worker` 是否在线且能连接数据库。
3. `bp_task` 的错误字段和 worker 日志。
4. 清洗行情是否已推进到预期交易日。
5. 任务是否因资产尾部缺口或优化失败而反复重试。

## 数据库

连接数据库：

```bash
set -a
source /opt/balanced-portfolio/.env
set +a

psql \
  -h "$PGHOST" \
  -p "$PGPORT" \
  -U "$PGUSER" \
  -d "$PGDATABASE"
```

全新环境只执行：

```bash
psql \
  -h "$PGHOST" \
  -p "$PGPORT" \
  -U "$PGUSER" \
  -d "$PGDATABASE" \
  -f ddl/schema.sql
```

已有环境升级时，只执行本环境尚未应用的新编号迁移。执行前必须备份并阅读 SQL；不要重新运行历史迁移清单，也不要直接改已应用脚本。

常用只读检查：

```sql
SELECT MAX(trade_date) FROM bp_quote_clean;

SELECT portfolio_id, status, data_as_of_date, error
FROM bp_portfolio
ORDER BY portfolio_id;

SELECT task_id, task_type, status, progress_message, error
FROM bp_task
ORDER BY created_at DESC
LIMIT 20;
```

不要用手工 `UPDATE` 把失败任务伪装为成功。先修复行情、配置或计算错误，再从产品界面或管理接口重新提交。

## Nginx

```bash
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl status nginx
sudo journalctl -u nginx --since "30 minutes ago"
```

路由必须保持：

```text
/api/session*  -> bp-web:3000
/api/*         -> bp-api:8000
/*             -> bp-web:3000
```

若登录返回 `404`，检查 `/api/session` 是否位于通用 `/api/` 规则之前，并确认前端已重新构建。

检查公网入口：

```bash
curl -I https://<your-domain>/
curl -fsS https://<your-domain>/api/health
curl -s -o /dev/null -w "%{http_code}\n" \
  https://<your-domain>/api/session
```

## 常见故障

### 页面无法打开

```bash
pm2 status
curl -I http://127.0.0.1:3000/
curl -fsS http://127.0.0.1:8000/api/health
sudo nginx -t
```

前端失败通常来自构建错误、PM2 环境变量未更新或 Nginx upstream 配置错误。

### 登录返回 404

`/api/session` 被错误转发到 FastAPI。按 `deploy/nginx.conf` 修正路由顺序，重新构建 `bp-web`，再重载 Nginx。

### 任务一直 queued

检查 Redis、`bp-worker` 和 `BP_TASK_MODE`。若开发环境不使用 Redis，应设置 `BP_TASK_MODE=inline` 并重启 API；生产环境不要长期依赖 inline 模式。

### 回测 status=error

先查看 API/worker 日志和组合错误字段。常见原因包括行情未拉全、资产尾部缺口、数据库连接失败或优化器输入无效。修复后重新提交回测。

### CFFEX 数据日期不一致

确认期货合约和四个挂钩指数都已更新到同一交易日，再运行一次 ingest。接口会拒绝用不同日期的现货和期货拼接快照。

### umami 有访客数但「回放(Replays)」一直是空的

回放**不是** `script.js` 的一个开关，而是独立的第二个 bundle `recorder.js`，必须单独注入。

**首要根因：生产还没发布带 recorder 注入的版本。** 只注入 `script.js` 的版本里，回放无论如何都不会有数据 —— 先确认线上 HTML 里真的有两个 tag，再往下查：

```bash
# 1) 页面里两个 tag 是否都在（只看到 script.js 就是还没发布 / 环境变量没进构建）
curl -s https://xushilu.com/ | grep -o 'umami[^ ]*\.js'
# 期望: script.js 与 recorder.js 各一

# 2) recorder bundle 是否可达
curl -sI https://umami.morean.cn/recorder.js | head -1

# 3) 该站点的回放开关是否真的开了（服务端配置）
curl -s "https://umami.morean.cn/api/websites/<WEBSITE_ID>/recorder"
# 期望: {"enabled":true,"replayEnabled":true,...}

# 4) 确认环境变量在构建时可见，然后重建 + 重启（见 .env 的 BP_UMAMI_* 三项）
grep -c BP_UMAMI_RECORDER_SRC .env && cd web && npm run build && pm2 restart bp-web --update-env
```

`BP_UMAMI_RECORDER_SRC` 留空时会由 `BP_UMAMI_SRC` 推导（把结尾的 `script.js` 换成 `recorder.js`）；两者相等时按禁用处理，不会重复注入第三个 tag。

浏览器 DevTools → Network 应能看到 `recorder.js`、`api/websites/<id>/recorder`、以及周期性的 `POST /api/record`。

前提条件：umami ≥ v3.1.0，且后台该站点已开启 Replays（采样率在后台配置，客户端不控制）。回放保留 30 天，只有加载了 recorder.js **之后**开始的会话才会被录到。

### 外币折算被覆写回原币口径（`bp_quote_clean` 里 HKD/VND 等价格突然变大）

**触发场景**：本地改了 `bp_api/quant/cleaning.py` 的清洗口径并跑了 `bp_ingest clean`，但**还没发布生产**。生产上的 `bp-ingest`（PM2 调度进程）跑的是部署时的旧版本，它会在下一个增量周期用旧代码重建同一批标的的清洗行，把折算结果覆写回原币口径。

**机制**：旧版本的 `_UPSERT_SQL` 的 `ON CONFLICT DO UPDATE SET` 列清单里没有 `fx_rate`，于是对已有行它只改 `close`（变回原币价），而 `fx_rate` 保持着你写进去的汇率 → 落成 `close/raw_close = 1.0 ≠ fx_rate` 的自相矛盾行；对它新插入的行该列为 NULL。

**判断**：
```sql
-- 脏行占比；正常应全为 0
SELECT c.symbol, COUNT(*) FROM bp_quote_clean c
  JOIN bp_index_quote_daily q USING (symbol, source, trade_date)
 WHERE c.fx_rate IS NOT NULL AND c.fx_rate <> 1
   AND abs(c.close / q.close - c.fx_rate) > 0.001
 GROUP BY 1 ORDER BY 2 DESC;
```

**处置**：先 `bash deploy/deploy.sh` 发布新代码，再重跑 `python -m bp_ingest clean --symbols <受影响 symbol>`。顺序反过来的话，清洗结果会在 ~40 分钟内再次被覆写。

`deploy.sh` 默认会 `pm2 stop` 全部进程再 `pm2 restart`，**全量重启会重新 import 代码**，因此发布后残留的旧模块不会继续运行。但要注意 `bp-api`/`bp-worker` 是常驻进程：如果用于手动重启（例如 `pm2 restart bp-ingest`）而**没走 deploy.sh**，先确认旧进程确实退出了再跑 clean。

注意 `pg_stat_activity.client_addr` 在生产与本地之间**无法用于区分**：经 Tailscale 连库时，本机与生产服务器在服务端看到的是同一个出口地址。

### 数据库锁或共享内存不足

先确认查询是否缺少日期范围，以及 TimescaleDB chunk 数量是否异常。生产参数调整和 chunk 合并会影响整个数据库，应在备份和维护窗口内由数据库管理员处理，不要在故障现场直接执行破坏性命令。

## 回滚

代码回滚应使用已经验证的发布版本或提交，并保持数据库向前兼容：

```bash
cd /opt/balanced-portfolio
git log --oneline -10
git switch --detach <known-good-commit>
BP_SKIP_PULL=1 bash deploy/deploy.sh
```

确认服务恢复后再决定分支处理。数据库迁移默认不自动回滚；涉及 schema 的版本必须事先准备并验证恢复方案。

## 安全检查

- `.env` 不进入 Git，文件权限限制为应用用户可读。
- 数据库和 Redis 不向公网开放。
- 生产环境显式设置随机 `BP_JWT_SECRET`。
- 管理员启用 TOTP。
- 日志和工单中不出现密码、token、Cookie、私有地址或客户数据。
- 定期备份 PostgreSQL，并验证恢复流程。
- 安全问题按 [SECURITY.md](../SECURITY.md) 私下报告。

## real-DB 语义测试（BP_TEST_DSN）

部分测试需要真实 PostgreSQL 验证语义，CI 无数据库时自动跳过，本地可选择性开启：

- `bp_api/tests/test_asset_status.py::test_with_count_semantics_real_db` — upsert/COUNT 语义
- `bp_api/tests/test_fx_cleaning.py::*_real_db` — 折算脏行清理判据（`close/raw_close == fx_rate`）
  与「不误删折算后的 interp 行」的行为回归。这条判据靠纯 mock 只能验 SQL 文本，验不了
  `NOT EXISTS` 在真实数据上的取舍，而它曾一次性误删过 1,402 行插值数据。

```bash
cd /opt/balanced-portfolio
source .venv/bin/activate
BP_TEST_DSN="postgresql://user:pass@localhost:5432/bp_tmp_test" \
  python -m pytest bp_api/tests/test_asset_status.py bp_api/tests/test_fx_cleaning.py -q
```

注意：

- DSN 内联在 URL 里时，密码中的 `@ : / # ?` 等特殊字符必须 URL 编码
  （`python -c "from urllib.parse import quote; print(quote('p@ss:word', safe=''))"`），
  或者改用 `PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE` 环境变量拼 libpq 连接。
- 不要直接指向生产库：测试会读写 `bp_asset_data_status` 测试行。推荐 scratch-DB 模式——
  建临时库、只建最小 schema、跑完即删。完整可复制流程（本节即按此流程验证过）：

```bash
set -a
source /opt/balanced-portfolio/.env   # 取 PGHOST/PGPORT/PGUSER/PGPASSWORD
set +a

# 1) 建临时库（连接 postgres 维护库，绝不写入业务数据）
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres \
  -c "CREATE DATABASE bp_tmp_test"

# 2) 建最小 schema（utf-8 临时文件 + psql -f；含中文注释亦可）
#    必须同时建 bp_index_quote_daily / bp_quote_clean 两张空普通表——
#    refresh_asset_status 两个分支在 upsert 前都会对两张表跑 MAX(trade_date)[, COUNT(*)]；
#    fx 清理判据（test_fx_cleaning.py）也要求 bp_quote_clean 带 fx_rate 列，否则整条
#    `abs(close/raw_close - fx_rate) <= 0.001` 等式无从验证。
#    不需要 TimescaleDB 扩展/hypertable，scratch 库只验 COUNT/MAX 与 upsert/清理谓词语义。
#    bp_asset_data_status 刻意不带指向 bp_data_source 的外键（生产 schema 有，见 ddl/schema.sql:387；
#    scratch 不建 bp_data_source、不种源行，测试用的 __T4_TEST__@__t4__ 直接可插）。
cat > /tmp/bp_tmp_test_schema.sql <<'SQL'
CREATE TABLE bp_index_quote_daily (
    trade_date    DATE          NOT NULL,
    symbol        TEXT          NOT NULL,
    source        TEXT          NOT NULL,
    close         NUMERIC(20,6) NOT NULL,
    CONSTRAINT pk_bp_index_quote_daily PRIMARY KEY (symbol, source, trade_date)
);

CREATE TABLE bp_quote_clean (
    trade_date  DATE          NOT NULL,
    symbol      TEXT          NOT NULL,
    source      TEXT          NOT NULL,
    close       NUMERIC(20,6) NOT NULL,
    fill_flag   TEXT          NOT NULL DEFAULT 'real',
    fx_rate     NUMERIC(20,10),
    CONSTRAINT pk_bp_quote_clean PRIMARY KEY (symbol, source, trade_date)
);

CREATE TABLE bp_asset_data_status (
    symbol          TEXT        NOT NULL,
    source          TEXT        NOT NULL,
    last_raw_date   DATE,
    last_clean_date DATE,
    raw_rows        BIGINT      NOT NULL DEFAULT 0,
    clean_rows      BIGINT      NOT NULL DEFAULT 0,
    last_success_at TIMESTAMPTZ,
    last_error      TEXT,
    last_probe_ms   INTEGER,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_bp_asset_data_status PRIMARY KEY (symbol, source)
);
SQL
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d bp_tmp_test \
  -v ON_ERROR_STOP=1 -f /tmp/bp_tmp_test_schema.sql

# 3) 密码 URL 编码后拼 DSN（密码含 @ : / # ? 时直接内联会被解析成坏 host）
BP_TEST_DSN="postgresql://$PGUSER:$(python -c \
  "import os; from urllib.parse import quote; print(quote(os.environ['PGPASSWORD'], safe=''))")\
@$PGHOST:$PGPORT/bp_tmp_test" \
  python -m pytest bp_api/tests/test_asset_status.py bp_api/tests/test_fx_cleaning.py -q
# 预期: 全部通过, 且 real-DB 各项为执行而非 skip（测试数随用例增减, 勿写死数字）

# 4) 跑完清理（DROP 临时库 + 删临时 SQL 文件）
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres \
  -c "DROP DATABASE bp_tmp_test"
rm -f /tmp/bp_tmp_test_schema.sql
```

- 未设置 `BP_TEST_DSN` 时这些测试一律 skip，`pytest -q` 与 CI 均不受影响
  （skip 数随带 `_real_db` 标记的用例增减, 勿写死数字）。
