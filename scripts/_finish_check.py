# -*- coding: utf-8 -*-
import os, paramiko, traceback
try:
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("81.71.158.239", username="root", password=os.environ.get("SSH_PASS",""), timeout=25, banner_timeout=25, auth_timeout=25)
    cmd = "date; echo '--- finish log ---'; tail -35 /tmp/round2_finish.log; echo '--- jobs ---'; pgrep -af 'round2_finish|index_quotes_free|repair_quote|daily_data_audit' || true"
    i,o,e=c.exec_command(cmd, timeout=60)
    print(o.read().decode("utf-8","replace")[:8000])
    c.close()
except Exception:
    traceback.print_exc()
