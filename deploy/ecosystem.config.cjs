/**
 * PM2 进程配置
 * 用法: APP_ROOT=/opt/balanced-portfolio pm2 start deploy/ecosystem.config.cjs
 */
const path = require("path");

const ROOT = process.env.APP_ROOT || path.join(__dirname, "..");
const VENV_PY = path.join(ROOT, ".venv", process.platform === "win32" ? "Scripts" : "bin", "python");
const VENV_UVICORN = path.join(ROOT, ".venv", process.platform === "win32" ? "Scripts" : "bin", "uvicorn");
const VENV_CELERY = path.join(ROOT, ".venv", process.platform === "win32" ? "Scripts" : "bin", "celery");

module.exports = {
  apps: [
    {
      name: "bp-api",
      cwd: ROOT,
      script: VENV_UVICORN,
      args: "bp_api.main:app --host 127.0.0.1 --port 8000",
      interpreter: "none",
      autorestart: true,
      max_restarts: 10,
      min_uptime: "10s",
      env: {
        NODE_ENV: "production",
      },
    },
    {
      name: "bp-web",
      cwd: path.join(ROOT, "web"),
      script: "npm",
      args: "run start",
      interpreter: "none",
      autorestart: true,
      max_restarts: 10,
      min_uptime: "10s",
      env: {
        NODE_ENV: "production",
        PORT: "3000",
        BP_API_BASE: process.env.BP_API_BASE || "http://127.0.0.1:8000",
        BP_SITE_URL: process.env.BP_SITE_URL || "http://localhost:3000",
      },
    },
    {
      name: "bp-ingest",
      cwd: ROOT,
      script: VENV_PY,
      args: "-m bp_ingest schedule",
      interpreter: "none",
      autorestart: true,
      max_restarts: 5,
      min_uptime: "30s",
      env: {
        NODE_ENV: "production",
      },
    },
    {
      name: "bp-worker",
      cwd: ROOT,
      script: VENV_CELERY,
      args: `-A bp_api.workers.celery_app.celery_app worker --loglevel=INFO --concurrency=${process.env.BP_CELERY_CONCURRENCY || "2"}`,
      interpreter: "none",
      autorestart: true,
      max_restarts: 10,
      min_uptime: "30s",
      env: {
        NODE_ENV: "production",
      },
    },
    {
      // Celery beat: 每 20 分钟巡检排队就绪组合的 T-1 自动更新。
      // 无 Redis 时可停用(bp-ingest 内已有 20 分钟兜底巡检)。
      name: "bp-beat",
      cwd: ROOT,
      script: VENV_CELERY,
      args: "-A bp_api.workers.celery_app.celery_app beat --loglevel=INFO",
      interpreter: "none",
      autorestart: true,
      max_restarts: 10,
      min_uptime: "30s",
      env: {
        NODE_ENV: "production",
      },
    },
  ],
};
