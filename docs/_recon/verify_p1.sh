#!/usr/bin/env bash
echo "--- counts ---"
bash /tmp/check_p1b.sh | tail -2
echo "--- detail api 930641 ---"
curl -s http://127.0.0.1:8000/api/valuation/930641 | .venv/bin/python -c "import sys,json; d=json.load(sys.stdin)['data']; print('constituents:', len(d.get('constituents') or []), 'funds:', len(d.get('tracker_funds') or [])); print('first:', (d.get('constituents') or [{}])[0]); print('fund:', (d.get('tracker_funds') or [{}])[0])"