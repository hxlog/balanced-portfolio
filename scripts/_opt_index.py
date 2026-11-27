# -*- coding: utf-8 -*-
import os, paramiko, traceback
try:
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("81.71.158.239", username="root", password=os.environ.get("SSH_PASS",""), timeout=25, banner_timeout=25, auth_timeout=25)
    cmd = '''cd /opt/balanced-portfolio
set -a; . ./.env; set +a
pgrep -f 'index_quotes_free.py --start' | xargs -r kill
sleep 2
echo KILLED_INDEX
rm -f /tmp/index_opt.log
setsid nohup .venv/bin/python scripts/index_quotes_free.py --start 2026-11-24 --source cn_index_tx cn_index_sina csindex_perf csindex_oss > /tmp/index_opt.log 2>&1 < /dev/null &
echo OPT_LAUNCHED
sleep 4
tail -8 /tmp/index_opt.log
echo '--- deploy running ---'
tail -8 /tmp/deploy_round2.log
'''
    i,o,e=c.exec_command(cmd, timeout=90)
    print(o.read().decode("utf-8","replace")[:5000]); print("ERR:", e.read().decode("utf-8","replace")[-500:])
    c.close()
except Exception:
    traceback.print_exc()
