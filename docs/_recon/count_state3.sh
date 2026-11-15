#!/usr/bin/env bash
cd /opt/balanced-portfolio
su - postgres -c "psql -d postgres -tAc \"select adjust, count(distinct symbol), count(*) from bp_stock_quote_daily group by 1\""
su - postgres -c "psql -d postgres -tAc \"select count(distinct fund_code), count(*) from bp_fund_nav_daily\""
