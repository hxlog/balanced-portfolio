#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "--- admin 相关配置 ---"
grep -E "^BP_(ADMIN|WHITELIST|ALLOW)" .env | sed "s/=.*/=<set>/"
echo "--- 管理员账号 ---"
su - postgres -c "psql -d postgres -tAc \"select email, is_admin, totp_enabled from bp_user order by user_id limit 5\""