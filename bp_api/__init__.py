"""Balanced Portfolio - 后端 API 与量化引擎包。

子模块:
    quant.cleaning  - 行情清洗(A股日历对齐 + 线性插值) → bp_quote_clean
    quant.optimizer - 组合权重优化(4 种方法 + sharpe/sortino)
    quant.backtest  - 无未来函数每日回测引擎
    quant.metrics   - 绩效指标与周期收益率/波动率
    repositories    - 数据访问层
    main            - FastAPI 应用
"""

__version__ = "1.0.0"
