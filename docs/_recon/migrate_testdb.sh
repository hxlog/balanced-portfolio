#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
for f in ddl/62_index_industry.sql ddl/63_percentile_windows.sql ddl/64_index_quote_extremes.sql; do
  echo "=== $f ==="
  su - postgres -c "psql -d bp_mig_test -v ON_ERROR_STOP=1 -f /opt/balanced-portfolio/$f" 2>&1 | tail -3
done
su - postgres -c "psql -d bp_mig_test -tAc \"select count(*) from information_schema.columns where table_name='bp_index_master' and column_name='industry'\""
su - postgres -c "psql -d bp_mig_test -tAc \"select count(*) from bp_index_quote_extremes\""
