#!/usr/bin/env bash
test_url() { curl -s -o /dev/null -w "%{http_code} %{time_total}" --max-time 12 "$1" || echo "fail"; }
echo -n "okx-ticker: "; test_url "https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT-SWAP"; echo
echo -n "bybit-ticker: "; test_url "https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT"; echo
echo -n "bybit-oi: "; test_url "https://api.bybit.com/v5/market/open-interest?category=linear&symbol=BTCUSDT&intervalTime=5min"; echo
echo -n "okx-oi: "; test_url "https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId=BTC-USDT-SWAP"; echo
echo -n "coinglass: "; test_url "https://open-api.coinglass.com/public/v2/funding"; echo