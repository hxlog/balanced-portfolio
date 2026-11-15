#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== 文件部署检查 ==="
grep -c "DashboardModeGate" web/app/dashboard/page.tsx || true
grep -c "UnifiedAssetsPanel" web/app/admin/assets/page.tsx || true
grep -c "资产池" web/components/Navbar.tsx || true
grep -c "require_asset_editor" bp_api/assets_unified.py || true
ls web/app/assets 2>/dev/null && echo "assets-still-exists" || echo "assets-removed"
echo "=== dashboard basket HTML ==="
curl -s --max-time 30 "http://127.0.0.1:3000/dashboard?mode=basket" -o /tmp/dashb.html -w "status:%{http_code} bytes:%{size_download}\n"
python3 - <<'PY'
html = open('/tmp/dashb.html', encoding='utf-8').read()
print('has-一篮子资产:', '一篮子资产' in html)
print('has-四象限组合:', '四象限组合' in html)
print('has-新建篮子:', '新建篮子' in html)
PY
echo "=== admin 页面 ==="
curl -s --max-time 30 "http://127.0.0.1:3000/admin/assets" -o /tmp/admin.html -w "status:%{http_code}\n"
python3 - <<'PY'
html = open('/tmp/admin.html', encoding='utf-8').read()
print('has-统一资产池:', '统一资产池' in html)
PY
