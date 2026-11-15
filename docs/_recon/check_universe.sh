#!/usr/bin/env bash
su - postgres -c "psql -d postgres -tAc \"select count(*) from bp_stock_master\""
su - postgres -c "psql -d postgres -tAc \"select count(*) from bp_fund_master\""
su - postgres -c "psql -d postgres -tAc \"select count(*) from bp_fund_nav_daily\""
