# -*- coding: utf-8 -*-
import os, paramiko, traceback
try:
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("81.71.158.239", username="root", password=os.environ.get("SSH_PASS",""), timeout=25, banner_timeout=25, auth_timeout=25)
    cmd = '''cd /opt/balanced-portfolio
set -a; . ./.env; set +a
timeout 600 .venv/bin/python scripts/index_quotes_free.py --symbols 000985 --start 2017-01-01 2>&1 | tail -8
psql -X -A -F '|' -c "select count(*),min(trade_date),max(trade_date) from bp_index_quote_daily where symbol='000985' and adjust='bfq'"
'''
    i,o,e=c.exec_command(cmd, timeout=660)
    print(o.read().decode("utf-8","replace")[:5000]); print("ERR:", e.read().decode("utf-8","replace")[-400:])
    c.close()
except Exception:
    traceback.print_exc()
