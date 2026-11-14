#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "--- market valuation rows ---"
su - postgres -c "psql -d postgres -tAc \"select board, pe_median, pe_equal, pb_median, sample_size, pct_pe from bp_market_valuation_daily order by board\""
echo "--- overview api ---"
curl -s http://127.0.0.1:8000/api/valuation/overview | head -c 600
echo
echo "--- p1 funds ---"
bash /tmp/check_p1.sh
echo "--- revalidate ---"
TOKEN=$(grep -m1 "^BP_INTERNAL_REVALIDATE_TOKEN=" .env | cut -d= -f2- | tr -d "\"\r ")
curl -s -X POST -H "X-Internal-Token: $TOKEN" http://127.0.0.1:3000/api/revalidate/valuation
echo