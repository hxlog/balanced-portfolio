#!/usr/bin/env bash
echo "--- bp-web log ---"
pm2 logs bp-web --lines 30 --nostream 2>/dev/null | tail -30