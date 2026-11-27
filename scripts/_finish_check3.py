# -*- coding: utf-8 -*-
import os, paramiko, traceback
try:
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("81.71.158.239", username="root", password=os.environ.get("SSH_PASS",""), timeout=25, banner_timeout=25, auth_timeout=25)
    cmd = "date; tail -12 /tmp/round2_finish.log; echo '--- jobs ---'; pgrep -af '[r]ound2_finish|[i]ndex_quotes_free|[r]epair_quote|[d]aily_data_audit' || true; ls -l /tmp/data_audit_round2.json 2>/dev/null"
    i,o,e=c.exec_command(cmd, timeout=60)
    print(o.read().decode("utf-8","replace")[:5000])
    c.close()
except Exception:
    traceback.print_exc()
