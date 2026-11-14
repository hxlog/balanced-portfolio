#!/usr/bin/env bash
set -euo pipefail
mkdir -p /opt/backups
TS=$(date +%Y%m%d_%H%M%S)
TMP="/tmp/pre_p0_$TS.dump"
OUT="/opt/backups/pre_p0_$TS.dump"
su - postgres -c "pg_dump -d postgres -Fc -f $TMP"
mv "$TMP" "$OUT"
ls -lh "$OUT"
echo "backup ok: $OUT"