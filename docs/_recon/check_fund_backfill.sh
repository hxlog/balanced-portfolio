#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== 基金回填 ==="
pgrep -fc backfill_fund_data || echo done
tail -4 /tmp/fund_backfill.log
su - postgres -c "psql -d postgres -tAc \"select count(*) filter (where management_fee is not null) fee_ok, count(*) filter (where established_date is not null) date_ok, count(*) filter (where manager is not null) mgr_ok, count(*) from bp_fund_master\""
su - postgres -c "psql -d postgres -tAc \"select count(*), count(ret_12m), count(ytd) from bp_fund_performance\""
