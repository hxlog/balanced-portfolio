#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "--- health ---"
curl -s -o /dev/null -w "api-health:%{http_code}\n" http://127.0.0.1:8000/api/health
echo "--- basket route (empty body -> 422) ---"
curl -s -o /dev/null -w "basket:%{http_code}\n" -X POST -H "Content-Type: application/json" -d '{}' http://127.0.0.1:8000/api/basket/optimize
echo "--- basket response body ---"
curl -s -X POST -H "Content-Type: application/json" -d '{"assets":[{"symbol":"000300","source":"cn_index_em"}],"method":"risk_parity","lookback_days":252,"risk_free":0.02}' http://127.0.0.1:8000/api/basket/optimize | head -c 400
echo
echo "--- crypto tables ---"
su - postgres -c "psql -d postgres -tAc \"select count(*) from bp_crypto_contract\""
su - postgres -c "psql -d postgres -tAc \"select count(*) from bp_crypto_futures_snapshot_5m\""