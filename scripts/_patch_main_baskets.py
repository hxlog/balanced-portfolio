# -*- coding: utf-8 -*-
p = "bp_api/main.py"
s = open(p, encoding="utf-8", newline="").read()
s = s.replace("    basket,\r\n", "    basket,\r\n    baskets,\r\n", 1)
if "baskets.register_routes(app)" not in s:
    s = s.replace("basket.register_routes(app)\r\n", "basket.register_routes(app)\r\nbaskets.register_routes(app)\r\n", 1)
open(p, "w", encoding="utf-8", newline="").write(s)
print("registered:", "baskets.register_routes" in s, "import:", "    baskets,\r\n" in s)
