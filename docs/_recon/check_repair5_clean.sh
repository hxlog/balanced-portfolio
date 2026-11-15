#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== 非 tqdm 行 ==="
tr -d "\r" < /tmp/repair_quotes5.log | tr "\r" "\n" | grep -avE "it/s|%\|" | grep -av "^$" | tail -20
echo "=== dmesg OOM ==="
dmesg 2>/dev/null | tail -5 | grep -i "killed\|oom" || echo "no oom"
free -m | head -2
