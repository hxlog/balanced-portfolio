# 部署文件

这里保存 Linux 生产环境使用的 PM2、Nginx 和发版脚本。首次安装、数据库初始化和安全配置见 [完整部署说明](../docs/deployment.md)。

- [deploy.sh](deploy.sh)：拉取代码、安装依赖、构建前端、重载 PM2 并执行健康检查。
- [ecosystem.config.cjs](ecosystem.config.cjs)：定义 API、Web、行情调度、Celery worker 和 beat 进程。
- [nginx.conf](nginx.conf)：Nginx 反向代理模板。使用前必须替换域名并配置 HTTPS。
- [OPS.md](OPS.md)：日常发版、状态检查和常见故障速查。

常规发版：

```bash
cd /opt/balanced-portfolio
bash deploy/deploy.sh
```

脚本不会自动执行数据库迁移。若版本包含新的编号迁移，应先备份数据库、审查迁移，再按发布说明单独执行。
