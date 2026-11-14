#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "--- bp_user 列 ---"
su - postgres -c "psql -d postgres -tAc \"select string_agg(column_name, chr(44)) from information_schema.columns where table_name = chr(98)||chr(112)||chr(95)||chr(117)||chr(115)||chr(101)||chr(114)\""
echo "--- 用户列表 ---"
su - postgres -c "psql -d postgres -tAc \"select * from bp_user limit 3\""