#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
.venv/bin/python - <<'PY'
import re, requests
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}
def strip(html):
    html = re.sub(r"<script[\s\S]*?</script>", " ", html)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html.replace("&nbsp;", " "))
r = requests.get("https://fundf10.eastmoney.com/jbgk_510300.html", headers=HEADERS, timeout=20)
text = strip(r.text)
for label in ("管理费率", "托管费率", "成立日期"):
    idx = text.find(label)
    print(label, "->", text[idx:idx+90] if idx >= 0 else "NOT FOUND")
PY
