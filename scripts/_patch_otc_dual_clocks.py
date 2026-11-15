# -*- coding: utf-8 -*-
p = "bp_api/quant/otc/pricer.py"
s = open(p, encoding="utf-8", newline="").read()

# 1) 双时钟参数
s = s.replace("""    day_count = DayCount(spec.get("day_count", "ACT365"))
    t_step = int(spec.get("t_step_per_year", 252))""",
"""    day_count = DayCount(spec.get("day_count", "ACT365"))
    # 金标准双时钟：折现（BUS252）与票息（ACT365）可不同；未显式指定时沿用 day_count。
    coupon_day_count = DayCount(spec.get("coupon_day_count", spec.get("day_count", "ACT365")))
    discount_day_count = DayCount(spec.get("discount_day_count", spec.get("day_count", "ACT365")))
    t_step = int(spec.get("t_step_per_year", 252))""")

# 2) 折现改用 discount_day_count
s = s.replace("mat_discount = _df(r, day_count, valuation, maturity, cal)",
              "mat_discount = _df(r, discount_day_count, valuation, maturity, cal)")
s = s.replace("ko_amounts = np.array([coupon_out * year_fraction(day_count, start, d, cal) * notional for d in ko_future])",
              "ko_amounts = np.array([coupon_out * year_fraction(coupon_day_count, start, d, cal) * notional for d in ko_future])")
s = s.replace("ko_discounts = np.array([_df(r, day_count, valuation, d, cal) for d in ko_future])",
              "ko_discounts = np.array([_df(r, discount_day_count, valuation, d, cal) for d in ko_future])")
s = s.replace("maturity_div_amount = coupon_div * year_fraction(day_count, start, maturity, cal) * notional",
              "maturity_div_amount = coupon_div * year_fraction(coupon_day_count, start, maturity, cal) * notional")
s = s.replace("discounts = np.array([_df(r, day_count, valuation, d, cal) for d in ko_future])",
              "discounts = np.array([_df(r, discount_day_count, valuation, d, cal) for d in ko_future])")

# 3) 解析解/积分法：t 用折现日计数（金标准气囊 ACT365 = 实际天数/365）
s = s.replace("""    if engine in (EngineType.ANALYTIC, EngineType.QUAD) and product in (ProductType.BARRIER, ProductType.AIRBAG):
        if product == ProductType.BARRIER:""",
"""    if engine in (EngineType.ANALYTIC, EngineType.QUAD) and product in (ProductType.BARRIER, ProductType.AIRBAG):
        t_year = year_fraction(discount_day_count, valuation, maturity, cal)
        if product == ProductType.BARRIER:""")

open(p, "w", encoding="utf-8", newline="").write(s)
print("dual clocks:", all(k in s for k in ("coupon_day_count", "discount_day_count")), "analytic t:", "t_year = year_fraction(discount_day_count" in s)
