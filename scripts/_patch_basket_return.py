# -*- coding: utf-8 -*-
import re
p = "bp_api/quant/basket.py"
s = open(p, encoding="utf-8", newline="").read()
pattern = re.compile(r"(        latest_drift=_safe_dict\(w_actual\.to_dict\(\)\),\r?\n        end_optimal_target=_safe_dict\(end_target\.to_dict\(\)\),\r?\n)(    \))")
replacement = (r"\1"
               "        equal_weight_nav=eq_series,\r\n"
               "        equal_weight_metrics={k: float(v) for k, v in eq_metrics.items() if isinstance(v, (int, float))},\r\n"
               r"\2")
new, count = pattern.subn(replacement, s)
open(p, "w", encoding="utf-8", newline="").write(new)
print("subs:", count, "has:", "equal_weight_nav=eq_series" in new)
