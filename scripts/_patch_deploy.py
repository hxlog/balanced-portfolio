# -*- coding: utf-8 -*-
import os, paramiko, traceback
try:
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("81.71.158.239", username="root", password=os.environ.get("SSH_PASS",""), timeout=25, banner_timeout=25, auth_timeout=25)
    cmd = "cd /opt/balanced-portfolio; date; git pull --ff-only 2>&1 | tail -2; pm2 restart bp-api --update-env >/dev/null 2>&1; echo API_RESTARTED; echo '--- deploy tail ---'; tail -40 /tmp/deploy_round2.log 2>/dev/null; echo '--- jobs ---'; pgrep -af 'index_quotes_free|backfill_legacy|repair_quote|valuation_run|compute_mvi|risk_free|market_valuation|seed_demo|daily_data_audit' || true; echo '--- health ---'; curl -s -m 5 http://127.0.0.1:8000/api/health; echo; curl -s -m 5 http://127.0.0.1:8000/api/v1/market/data-freshness | head -c 300"
    i,o,e=c.exec_command(cmd, timeout=90)
    print(o.read().decode("utf-8","replace")[:10000])
    c.close()
except Exception:
    traceback.print_exc()
