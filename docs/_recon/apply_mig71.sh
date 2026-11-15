#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
su - postgres -c "psql -d postgres -v ON_ERROR_STOP=1 -f /opt/balanced-portfolio/ddl/71_stock_quotes.sql" 2>&1 | tail -2
su - postgres -c "psql -d postgres -tAc \"select count(*) from bp_stock_quote_daily\""
