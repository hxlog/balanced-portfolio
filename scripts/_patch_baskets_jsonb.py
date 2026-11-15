# -*- coding: utf-8 -*-
p = "bp_api/baskets.py"
s = open(p, encoding="utf-8").read()
s = s.replace("from fastapi import Depends, FastAPI, HTTPException",
              "from fastapi import Depends, FastAPI, HTTPException\nfrom psycopg.types.json import Jsonb")
# create
s = s.replace('''                    _json_safe(assets),
                    _json_safe(payload.params or {}),
                    _json_safe(payload.latest_result) if payload.latest_result else None,''',
'''                    Jsonb(_json_safe(assets)),
                    Jsonb(_json_safe(payload.params or {})),
                    Jsonb(_json_safe(payload.latest_result)) if payload.latest_result else None,''')
# update
s = s.replace('''                values.append(_json_safe([{"symbol": a.symbol, "source": a.source} for a in payload.assets]))''',
'''                values.append(Jsonb(_json_safe([{"symbol": a.symbol, "source": a.source} for a in payload.assets])))''')
s = s.replace('''                values.append(_json_safe(payload.params))''',
'''                values.append(Jsonb(_json_safe(payload.params)))''')
s = s.replace('''                values.append(_json_safe(payload.latest_result))''',
'''                values.append(Jsonb(_json_safe(payload.latest_result)))''')
# copy
s = s.replace('''                    _json_safe(basket.get("assets")),
                    _json_safe(basket.get("params")),
                    _json_safe(basket.get("latest_result")) if basket.get("latest_result") else None,''',
'''                    Jsonb(_json_safe(basket.get("assets"))),
                    Jsonb(_json_safe(basket.get("params"))),
                    Jsonb(_json_safe(basket.get("latest_result"))) if basket.get("latest_result") else None,''')
open(p, "w", encoding="utf-8").write(s)
print("Jsonb patched:", s.count("Jsonb("))
