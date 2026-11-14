#!/usr/bin/env bash
for i in $(seq 1 30); do
  n=$(ps aux | grep -c "[v]aluation_run")
  if [ "$n" -eq 0 ]; then echo "finished at $i"; break; fi
  sleep 5
done
tail -2 /tmp/valuation_ingest4.log
bash /tmp/check_p1.sh