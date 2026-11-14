#!/usr/bin/env bash
echo "--- grep constraint/conflict ---"
grep -icE "no unique constraint|ON CONFLICT|adjust" /root/.pm2/logs/bp-ingest-error.log 2>/dev/null || echo 0
grep -iE "no unique constraint|ON CONFLICT" /root/.pm2/logs/bp-ingest-error.log 2>/dev/null | tail -3
echo "--- recent run results ---"
grep -E "增量完成|同步完成|失败" /root/.pm2/logs/bp-ingest-out.log 2>/dev/null | tail -5