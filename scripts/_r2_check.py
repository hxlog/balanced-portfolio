# -*- coding: utf-8 -*-
import os, paramiko, traceback
try:
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("81.71.158.239", username="root", password=os.environ.get("SSH_PASS",""), timeout=25, banner_timeout=25, auth_timeout=25)
    cmd = "date; echo '--- deploy tail ---'; tail -80 /tmp/deploy_round2.log 2>/dev/null; echo '--- running jobs ---'; pgrep -af 'index_quotes_free|backfill_legacy|repair_quote|valuation_run|compute_mvi|risk_free|market_valuation|seed_demo|daily_data_audit|deploy_round2' || true; echo '--- pm2 ---'; pm2 status | head -12; free -m | head -2"
    i,o,e=c.exec_command(cmd, timeout=60)
    print(o.read().decode("utf-8","replace")[:14000])
    c.close()
except Exception:
    traceback.print_exc()
