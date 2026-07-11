"""OTC 定价枚举 (对齐 pricelib 术语)。"""

from __future__ import annotations

from enum import Enum


class ProductType(str, Enum):
    SNOWBALL = "snowball"   # 雪球 (经典/含红利)
    PHOENIX = "phoenix"     # 凤凰
    AIRBAG = "airbag"       # 安全气囊
    BARRIER = "barrier"     # 单边障碍期权


class EngineType(str, Enum):
    MC = "mc"               # 蒙特卡洛
    ANALYTIC = "analytic"   # 闭式解 BSM 解析 (障碍/气囊, 连续观察)
    QUAD = "quad"           # 积分法 数值积分 (障碍/气囊, 离散/连续)
    PDE = "pde"             # 有限差分 (v1 未实现, 回退 MC)


class Direction(str, Enum):
    BUY = "buy"             # 买入 (投资者持有, +PV)
    SELL = "sell"           # 卖出 (-PV)


class CallPut(str, Enum):
    CALL = "call"
    PUT = "put"


class UpDown(str, Enum):
    UP = "up"
    DOWN = "down"


class InOut(str, Enum):
    IN = "in"
    OUT = "out"


class DealStatus(str, Enum):
    ALIVE = "alive"                 # 存续中
    KNOCKED_IN = "knocked_in"       # 已敲入(未敲出, 存续)
    KNOCKED_OUT = "knocked_out"     # 已敲出(终止)
    EXPIRED = "expired"             # 已到期


class DayCount(str, Enum):
    ACT365 = "ACT365"
    ACT360 = "ACT360"
    BUS252 = "BUS252"


def sign_of(direction: "Direction | str") -> float:
    d = direction.value if isinstance(direction, Direction) else str(direction)
    return 1.0 if d == Direction.BUY.value else -1.0
