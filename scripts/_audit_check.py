# -*- coding: utf-8 -*-
import os, json, paramiko, traceback
try:
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("81.71.158.239", username="root", password=os.environ.get("SSH_PASS",""), timeout=25, banner_timeout=25, auth_timeout=25)
    cmd = "cat /tmp/data_audit_round2.json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({\"summary\":d.get(\"summary\"),\"exit_code\":d.get(\"exit_code\"),\"checks\":[c for c in d.get(\"checks\",[]) if c.get(\"status\")!=\"ok\"]}, ensure_ascii=False, indent=1)[:4000])'"
    i,o,e=c.exec_command(cmd, timeout=60)
    print(o.read().decode("utf-8","replace")[:5000]); print("ERR:", e.read().decode("utf-8","replace")[-500:])
    c.close()
except Exception:
    traceback.print_exc()
