# -*- coding: utf-8 -*-
p = "bp_api/quant/otc/engine.py"
s = open(p, encoding="utf-8", newline="").read()
s = s.replace("""    return float(call_parti * cdo + reset_call_parti * cdi - knockin_parti * pdi)""",
"""    # 金标（镒链 202104130944 / QuantLib AnalyticBarrierEngine）：
    #   气囊 = 敲入参与率 × (下入看涨 − 下入看跌) + 参与率 × 下出看涨
    # 即 cdi/pdi 的系数统一为 knockin_parti（reset_call_parti 仅用于 MC payoff 兼容）。
    return float(knockin_parti * (cdi - pdi) + call_parti * cdo)""")
open(p, "w", encoding="utf-8", newline="").write(s)
print("airbag formula patched:", "knockin_parti * (cdi - pdi)" in s)
