#!/usr/bin/env bash
echo "--- bp-ingest errors since 18:20 ---"
pm2 logs bp-ingest --lines 400 --nostream 2>/dev/null | grep -iE "error|conflict|exception|traceback" | tail -8 || echo none
echo "--- last ingest lines ---"
pm2 logs bp-ingest --lines 15 --nostream 2>/dev/null | tail -8