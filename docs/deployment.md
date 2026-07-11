# 部署说明

本文说明如何手工部署 Balanced Portfolio。项目当前不提供 Docker 编排；生产模板采用 Linux、PM2 和 Nginx。

## 1. 准备环境

建议使用一台应用服务器和一套 PostgreSQL/TimescaleDB 数据库。最低软件要求：

- Python 3.11–3.14
- Node.js 20+
- PostgreSQL 18
- TimescaleDB 2.23+
- Redis
- PM2、Nginx、`psql`、Git

数据库应只允许应用服务器或内网访问，不要向公网开放 `5432`。应用服务器只需公开 `80` 和 `443`。

## 2. 获取代码

```bash
sudo mkdir -p /opt/balanced-portfolio
sudo chown "$USER:$USER" /opt/balanced-portfolio
git clone https://github.com/hxlog/balanced-portfolio.git /opt/balanced-portfolio
cd /opt/balanced-portfolio
```

创建 Python 虚拟环境并安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd web
npm ci --legacy-peer-deps
cd ..
```

## 3. 配置环境变量

```bash
cp .env.example .env
chmod 600 .env
```

至少检查以下配置：

```env
PGHOST=<database-host>
PGPORT=5432
PGDATABASE=<database-name>
PGUSER=<database-user>
PGPASSWORD=<strong-database-password>

BP_CORS_ORIGINS=https://<your-domain>
BP_JWT_SECRET=<random-long-secret>
BP_ADMIN_EMAIL=<admin@example.com>
BP_ADMIN_INITIAL_PASSWORD=<initial-admin-password>
BP_API_BASE=http://127.0.0.1:8000
BP_SITE_URL=https://<your-domain>

REDIS_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
BP_TASK_MODE=celery
```

不要提交 `.env`。生产环境必须显式设置随机的 `BP_JWT_SECRET`，不要依赖数据库密码派生。`BP_ADMIN_INITIAL_PASSWORD` 只在首次创建管理员时使用，创建成功并修改密码后可从运行环境移除。

## 4. 初始化数据库

全新数据库只执行合并后的 schema：

```bash
set -a
source .env
set +a

# 数据库尚未创建时，先使用具备 CREATEDB 权限的账号执行：
createdb -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$PGDATABASE"

psql \
  -h "$PGHOST" \
  -p "$PGPORT" \
  -U "$PGUSER" \
  -d "$PGDATABASE" \
  -f ddl/schema.sql
```

数据库已经存在时跳过 `createdb`；应用账号没有建库权限时，由数据库管理员预先创建数据库和扩展。

不要在全新数据库上再重复执行旧编号脚本。已有部署升级时，只执行尚未应用的新编号迁移；数据库变更纪律见 [CONTRIBUTING.md](../CONTRIBUTING.md)。

验证连接并完成首轮行情：

```bash
source .venv/bin/activate
python -m bp_ingest ping
python -m bp_ingest run
```

首轮拉取耗时取决于资产数量、起始日期和上游限流。遇到单一资产失败时，先核对资产代码和 AKShare 接口，不要直接跳过清洗错误。

## 5. 构建并启动服务

项目提供 PM2 配置，包含：

- `bp-api`：FastAPI，监听 `127.0.0.1:8000`
- `bp-web`：Next.js，监听 `127.0.0.1:3000`
- `bp-ingest`：行情定时更新
- `bp-worker`：Celery worker
- `bp-beat`：Celery 定时巡检

```bash
cd /opt/balanced-portfolio
export APP_ROOT=/opt/balanced-portfolio
set -a
source .env
set +a

cd web
npm run build
cd ..

pm2 start deploy/ecosystem.config.cjs
pm2 save
pm2 startup
```

`pm2 startup` 会输出一条需要 `sudo` 执行的命令，按终端提示完成即可。

## 6. 配置 Nginx 与 HTTPS

复制模板并替换域名：

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/balanced-portfolio
sudo editor /etc/nginx/sites-available/balanced-portfolio
sudo ln -s /etc/nginx/sites-available/balanced-portfolio \
  /etc/nginx/sites-enabled/balanced-portfolio
sudo nginx -t
sudo systemctl reload nginx
```

模板中最重要的是 Session 路由顺序：

```nginx
location /api/session {
    proxy_pass http://bp_web;
}

location /api/ {
    proxy_pass http://bp_api;
}
```

`/api/session` 必须写在通用 `/api/` 之前，并转给 Next.js。它负责写入 httpOnly Cookie；FastAPI 没有这个路由。

确认 HTTP 可访问后，用 Certbot 或现有证书系统启用 HTTPS：

```bash
sudo certbot --nginx -d <your-domain>
sudo certbot renew --dry-run
```

## 7. 发布更新

服务器端发版脚本会拉取代码、更新 Python 和前端依赖、构建前端、重载 PM2、执行健康检查并在配置有效时重载 Nginx：

```bash
cd /opt/balanced-portfolio
bash deploy/deploy.sh
```

发版前应在开发或 CI 环境执行：

```bash
python -m pytest bp_api/tests -q
cd web && npm run build
```

如果版本包含新的编号数据库迁移，先阅读迁移内容并安排备份和维护窗口，再对已有数据库单独执行。`deploy.sh` 不会自动执行数据库迁移。

## 8. 发布后检查

```bash
pm2 status
curl -fsS http://127.0.0.1:8000/api/health
curl -s -o /dev/null -w "%{http_code}\n" \
  http://127.0.0.1:3000/api/session
sudo nginx -t
redis-cli ping
```

未登录时 Session 地址应返回鉴权相关状态，不能是 `404`。同时检查：

- `bp-api`、`bp-web`、`bp-ingest`、`bp-worker`、`bp-beat` 均为 `online`。
- 首页和 API 可通过 HTTPS 访问。
- 新建组合能从 `queued/running` 进入 `done`。
- 行情最新日期和组合 `data_as_of_date` 符合预期。
- 日志中没有持续的数据库连接、上游限流或任务重试错误。

常用排障命令见 [生产运维速查](../deploy/OPS.md)。

## 9. 安全基线

- 只从受信任网络开放 SSH，数据库仅允许内网连接。
- `.env` 权限设为应用用户可读，定期轮换数据库密码和 JWT 密钥。
- 管理员首次登录后立即绑定 TOTP。
- 为 PostgreSQL、Redis 和应用数据建立定期备份，并实际演练恢复。
- Nginx、Node.js、Python、PostgreSQL、Redis 及依赖要持续安装安全更新。
- 上线前确认 `BP_CORS_ORIGINS` 只包含实际 HTTPS 域名。
- 不在日志、Issue、截图或运维文档中粘贴 token、Cookie、密码、私有地址和真实客户数据。
