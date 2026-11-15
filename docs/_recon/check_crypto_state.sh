#!/usr/bin/env bash
echo "=== /crypto 页面关键内容 ==="
curl -s --max-time 20 http://127.0.0.1:3000/crypto | grep -oE "加密货币看板|相关性|BTC|ETH|样本不足|暂无|Coming soon|敬请期待" | sort | uniq -c | head -10
echo "=== /crypto-futures 页面关键内容 ==="
curl -s --max-time 20 http://127.0.0.1:3000/crypto-futures | grep -oE "加密合约看板|多空比|持仓量|合约监控|暂无|样本" | sort | uniq -c | head -10
echo "=== crypto snapshot 最新 ==="
su - postgres -c "psql -d postgres -tAc \"select count(*), max(captured_at) from bp_crypto_futures_snapshot_5m\""
echo "=== crypto corr 表 ==="
su - postgres -c "psql -d postgres -tAc \"select count(*), max(trade_date) from bp_crypto_corr_daily\"" 2>/dev/null || echo "no corr table"
