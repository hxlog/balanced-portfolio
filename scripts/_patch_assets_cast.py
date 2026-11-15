# -*- coding: utf-8 -*-
p = "bp_api/assets_unified.py"
s = open(p, encoding="utf-8").read()
s = s.replace("(%(keyword)s = ''", "(%(keyword)s::text = ''")
s = s.replace("(%(market)s IS NULL OR upper(COALESCE(m.market, '')) = %(market)s)",
              "(%(market)s::text IS NULL OR upper(COALESCE(m.market, '')) = %(market)s::text)")
open(p, "w", encoding="utf-8").write(s)
print("cast patched:", "market)s::text IS NULL" in s)
