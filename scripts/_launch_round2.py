# -*- coding: utf-8 -*-
import os, paramiko, traceback
try:
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("81.71.158.239", username="root", password=os.environ.get("SSH_PASS",""), timeout=25, banner_timeout=25, auth_timeout=25)
    sftp=c.open_sftp(); sftp.put(r"D:\balanced-portfolio\scripts\_deploy_round2.sh", "/tmp/deploy_round2.sh"); sftp.close()
    i,o,e=c.exec_command("chmod +x /tmp/deploy_round2.sh; rm -f /tmp/deploy_round2.log; setsid nohup bash /tmp/deploy_round2.sh > /tmp/deploy_round2.log 2>&1 < /dev/null & echo ROUND2_DEPLOY_LAUNCHED; sleep 5; head -8 /tmp/deploy_round2.log", timeout=60)
    print(o.read().decode("utf-8","replace")[:2500])
    c.close()
except Exception:
    traceback.print_exc()
