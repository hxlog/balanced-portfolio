#!/usr/bin/env bash
echo "=== 页面 ==="
for p in /valuation /valuation/000300 /crypto-futures /crypto; do
  curl -s -o /dev/null -w "  $p -> %{http_code} %{time_total}s\n" --max-time 40 "http://127.0.0.1:3000$p"
done
echo "=== 数据 ==="
su - postgres -c "psql -d postgres -tAc \"select count(*) filter (where industry is not null), count(*) from bp_index_master where is_active and is_tracked\""
su - postgres -c "psql -d postgres -tAc \"select window_key, count(*) filter (where pct is not null) from bp_index_percentile where as_of_date = (select max(as_of_date) from bp_index_percentile) group by 1 order by 1\""
su - postgres -c "psql -d postgres -tAc \"select count(*) from bp_crypto_futures_snapshot_5m\""
su - postgres -c "psql -d postgres -tAc \"select window_days, count(*), min(sample_size), max(sample_size) from bp_crypto_futures_percentile group by 1 order by 1\""
