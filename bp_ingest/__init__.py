"""Balanced Portfolio - 基础数据落库与增量更新包。

模块:
    config      - 运行配置(从环境变量/.env 读取)
    db          - PostgreSQL/TimescaleDB 访问层
    sources     - akshare 数据源适配器注册表
    calendar    - A股交易日历
    ingest      - 增量更新引擎
    scheduler   - 定时调度(每 6h)
    cli         - 命令行入口
"""

__version__ = "1.0.0"
