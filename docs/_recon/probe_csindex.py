# -*- coding: utf-8 -*-
import inspect, akshare as ak
src = inspect.getsource(ak.stock_zh_index_value_csindex)
print(src[:3500])
print("FILE:", inspect.getsourcefile(ak.stock_zh_index_value_csindex))
