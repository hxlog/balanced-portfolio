#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== basket optimize (4 assets) ==="
curl -s -X POST -H "Content-Type: application/json" -d '{"assets":[{"symbol":"000300","source":"cn_index_em"},{"symbol":"000905","source":"cn_index_em"},{"symbol":"HSI","source":"hk_index_em"},{"symbol":"GOLD","source":"gold_comex_em"}],"method":"risk_parity","lookback_days":252,"risk_free":0.02}' http://127.0.0.1:8000/api/basket/optimize | head -c 500
echo
echo "=== basket backtest ==="
curl -s -X POST -H "Content-Type: application/json" -d '{"assets":[{"symbol":"000300","source":"cn_index_em"},{"symbol":"000905","source":"cn_index_em"}],"method":"max_sharpe","lookback_days":252,"risk_free":0.02,"rebalance_band":0.05}' http://127.0.0.1:8000/api/basket/backtest | head -c 400
echo
echo "=== equal weight ==="
curl -s -X POST -H "Content-Type: application/json" -d '{"assets":[{"symbol":"000300","source":"cn_index_em"},{"symbol":"HSI","source":"hk_index_em"}],"method":"equal_weight","lookback_days":120,"risk_free":0.02}' http://127.0.0.1:8000/api/basket/optimize | head -c 300