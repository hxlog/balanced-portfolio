#!/usr/bin/env bash
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
echo "=== 天天基金 f10 基本信息 ==="
curl -s -o /tmp/f10.txt -w "fundf10 jbgk: %{http_code} %{size_download}\n" --max-time 20 -A "$UA" "https://fundf10.eastmoney.com/jbgk_510300.html"
grep -oE "管理费率|托管费率|成立日期|基金规模|基金经理" /tmp/f10.txt | sort | uniq -c | head
echo "=== 天天基金移动 API ==="
curl -s -o /tmp/fm.txt -w "fundmobapi: %{http_code} %{size_download}\n" --max-time 20 -A "$UA" "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNNBasicInformation?FCODE=510300&deviceid=Wap&plat=Wap&product=EFund&version=2.0.0"
head -c 400 /tmp/fm.txt
echo
echo "=== 中证官网 indicator 字段 ==="
cd /opt/balanced-portfolio
.venv/bin/python - <<'PY'
from bp_ingest.config import load_config
from bp_ingest.db import connect
app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("select column_name from information_schema.columns where table_name='bp_index_csindex_value' order by ordinal_position")
    print("csindex_value:", [r[0] for r in cur.fetchall()])
PY
