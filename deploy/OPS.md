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
