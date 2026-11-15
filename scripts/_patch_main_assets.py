# -*- coding: utf-8 -*-
p = "bp_api/main.py"
s = open(p, encoding="utf-8", newline="").read()
if "assets_unified" not in s:
    s = s.replace("from . import valuation\r\n", "from . import valuation\r\nfrom . import assets_unified\r\n")
    s = s.replace("valuation.register_routes(app)\r\n", "valuation.register_routes(app)\r\nassets_unified.register_routes(app)\r\n")
open(p, "w", encoding="utf-8", newline="").write(s)
print("registered:", "assets_unified.register_routes" in s)
