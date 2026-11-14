#!/usr/bin/env bash
ps aux | grep "[v]aluation_run" || echo no-proc
echo "--- net ---"
ss -tnp 2>/dev/null | grep -c pingan || true
echo "--- pg ---"
su - postgres -c "psql -d postgres -tAc \"select coalesce(state,chr(45)), count(*) from pg_stat_activity group by 1\""
echo "--- log size ---"
wc -l /tmp/valuation_ingest.log