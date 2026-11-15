#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== pm2 env secret ==="
pm2 env 0 2>/dev/null | grep "BP_JWT_SECRET" | head -2 | sed 's/\(BP_JWT_SECRET=.\{6\}\).*/\1.../'
echo "=== .env secret ==="
grep "^BP_JWT_SECRET=" .env | sed 's/\(BP_JWT_SECRET=.\{6\}\).*/\1.../'
echo "=== auth helper ==="
sed -n '150,200p' bp_api/auth.py
