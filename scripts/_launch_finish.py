# -*- coding: utf-8 -*-
import os, paramiko, traceback
try:
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("81.71.158.239", username="root", password=os.environ.get("SSH_PASS",""), timeout=25, banner_timeout=25, auth_timeout=25)
    sftp=c.open_sftp(); sftp.put(r"D:\balanced-portfolio\scripts\_round2_finish.sh", "/tmp/round2_finish.sh"); sftp.close()
    i,o,e=c.exec_command("chmod +x /tmp/round2_finish.sh; rm -f /tmp/round2_finish.log; setsid nohup bash /tmp/round2_finish.sh > /tmp/round2_finish.log 2>&1 < /dev/null & echo FINISH_LAUNCHED; sleep 4; tail -3 /tmp/round2_finish.log", timeout=60)
    print(o.read().decode("utf-8","replace")[:1500])
    c.close()
except Exception:
    traceback.print_exc()
