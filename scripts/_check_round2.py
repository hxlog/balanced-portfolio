# -*- coding: utf-8 -*-
import os, paramiko, traceback
try:
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("81.71.158.239", username="root", password=os.environ.get("SSH_PASS",""), timeout=25, banner_timeout=25, auth_timeout=25)
    cmd = "date; echo '--- deploy log tail ---'; tail -60 /tmp/deploy_round2.log 2>/dev/null; echo '--- pm2 ---'; pm2 status | head -14; echo '--- health ---'; curl -s -m 5 http://127.0.0.1:8000/api/health; echo; curl -s -m 5 -o /dev/null -w 'web=%{http_code}\n' http://127.0.0.1:3000/"
    i,o,e=c.exec_command(cmd, timeout=60)
    print(o.read().decode("utf-8","replace")[:12000])
    c.close()
except Exception:
    traceback.print_exc()
