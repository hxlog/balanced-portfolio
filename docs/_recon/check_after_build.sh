#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
ls -lh web/core.* 2>/dev/null | head -3
rm -f web/core.* && echo 'core dumps removed'
echo '--- backfill ---'
tail -2 /tmp/valuation_backfill.log
pgrep -f 'bp_ingest run' > /dev/null && echo 'backfill running' || echo 'backfill finished'
echo '--- coverage ---'
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_quote_clean where adjust = 'bfq' and symbol in (select index_code from bp_index_master where is_tracked)\""
date