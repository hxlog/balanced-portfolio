# -*- coding: utf-8 -*-
import os, paramiko, traceback
try:
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("81.71.158.239", username="root", password=os.environ.get("SSH_PASS",""), timeout=25, banner_timeout=25, auth_timeout=25)
    cmd = '''cd /opt/balanced-portfolio
set -a; . ./.env; set +a
timeout 300 .venv/bin/python scripts/index_quotes_free.py --symbols 930604 931230 H30533 970081 --start 2026-11-24 --source cn_index_tx cn_index_sina csindex_perf csindex_oss 2>&1 | tail -40
'''
    i,o,e=c.exec_command(cmd, timeout=360)
    print(o.read().decode("utf-8","replace")[:8000])
    c.close()
except Exception:
    traceback.print_exc()
