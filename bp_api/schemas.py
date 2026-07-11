"""API 请求/响应模型(pydantic v2)。"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

Quadrant = str  # overheat / stagflation / recovery / recession
Method = str
Ratio = str

DEFAULT_MAX_WEIGHT = 1.0 / 3.0
DEFAULT_BENCHMARK_KEY = "bond6040"
DEFAULT_DESCRIPTION = "组合描述"


class AssetOut(BaseModel):
    symbol: str
    source: str
    category: Optional[str] = None
    name: Optional[str] = None
    asset_class: Optional[str] = None
    vendor: Optional[str] = None       # 数据供应商中文短名(东财/新浪/腾讯/中金所/中债)
    adjust: Optional[str] = None       # 复权类型: bfq/qfq/hfq(仅 ETF 有; None 表示不复权/不适用)


class AssetIn(BaseModel):
    symbol: str
    source: str
    quadrant: Quadrant
    display_name: Optional[str] = None


class PortfolioPayloadBase(BaseModel):
    name: str = Field(default="我的组合")
    description: str = Field(default=DEFAULT_DESCRIPTION)
    method: Method = "quadrant_inner_sharpe_outer_rp"
    ratio: Ratio = "sharpe"
    lookback_days: int = 156
    start_date: date
    benchmark_key: str = DEFAULT_BENCHMARK_KEY
    max_weight: float = Field(default=DEFAULT_MAX_WEIGHT, gt=0, le=1)
    rebalance_band: float = 0.05
    risk_free_rate: Optional[float] = None
    # 手续费(双边, 万分之几): 买入/卖出均缴; 默认万1.5 = 0.00015
    fee_rate: float = Field(default=0.00015, ge=0, le=0.1)
    # 滑点(双边, 买卖均缴); 默认万1.5 = 0.00015
    slippage_rate: float = Field(default=0.00015, ge=0, le=0.1)
    # 印花税(单边, 仅卖出): A股默认 0.05% = 0.0005
    stamp_duty_rate: float = Field(default=0.0005, ge=0, le=0.01)
    assets: list[AssetIn]

    @field_validator("max_weight")
    @classmethod
    def _max_weight_range(cls, v: float) -> float:
        if not (0 < v <= 1):
            raise ValueError("单资产最大权重须在 (0, 1] 之间")
        return v

    @field_validator("risk_free_rate")
    @classmethod
    def _risk_free_default(cls, v: Optional[float]) -> Optional[float]:
        return v

    @model_validator(mode="after")
    def _risk_free_required_for_sharpe(self):
        if self.ratio == "sharpe" and self.risk_free_rate is None:
            raise ValueError("选择夏普比率时必须填写无风险利率")
        if self.risk_free_rate is None:
            self.risk_free_rate = 0.0
        return self


class CreatePortfolioIn(PortfolioPayloadBase):
    pass


class UpdatePortfolioIn(PortfolioPayloadBase):
    pass


class LoginIn(BaseModel):
    email: str
    password: str
    otp_code: Optional[str] = None


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str


class CreateUserIn(BaseModel):
    email: str
    password: str


class UpdateUserIn(BaseModel):
    portfolio_limit: Optional[int] = None
    status: Optional[str] = None


class SetDemoIn(BaseModel):
    is_demo: bool


class PortfolioMetaIn(BaseModel):
    name: str
    description: str


class CopyPortfolioIn(BaseModel):
    name: Optional[str] = None


class ReorderPortfoliosIn(BaseModel):
    ordered_ids: list[int]


class VerifyTotpIn(BaseModel):
    code: str


class SetupTotpIn(BaseModel):
    current_code: Optional[str] = None


class DisableTotpIn(BaseModel):
    code: str


class AssetAdminIn(BaseModel):
    symbol: str
    source: str
    name: str
    category: Optional[str] = None
    start_date: Optional[date] = None
    is_deleted: int = 0
    adjust: Optional[str] = None      # 复权: bfq/qfq/hfq; 仅 ETF 类目生效, 写入 extra_params


class AssetSelectableIn(BaseModel):
    selectable: bool


class TaskOut(BaseModel):
    task_id: str
    task_type: str
    status: str
    portfolio_id: Optional[int] = None
    progress_current: int = 0
    progress_total: int = 1
    progress_message: Optional[str] = None
    result: dict = {}
    error: Optional[str] = None


class PortfolioOut(BaseModel):
    portfolio_id: int
    name: str
    method: str
    ratio: str
    lookback_days: int
    start_date: date
    effective_start_date: Optional[date] = None
    benchmark_symbol: str
    benchmark_source: str
    is_demo: bool
    status: str
    owner_user_id: Optional[int] = None
    risk_free_rate: float = 0
    fee_rate: float = 0
    slippage_rate: float = 0
    stamp_duty_rate: float = 0
    result_version: int = 1
    result_updated_at: Optional[str] = None
    data_as_of_date: Optional[date] = None
    error: Optional[str] = None
    assets: list[dict] = []


class NavPoint(BaseModel):
    trade_date: date
    nav: float
    benchmark_nav: Optional[float] = None
    ret: Optional[float] = None
    bench_ret: Optional[float] = None


class RebalanceOut(BaseModel):
    trade_date: date
    reason: Optional[str]
    target_weights: dict
    prev_weights: Optional[dict] = None
    delta: Optional[dict] = None
    quadrant_weights: Optional[dict] = None
    max_deviation: Optional[float] = None


class ResultOut(BaseModel):
    portfolio: PortfolioOut
    nav: list[NavPoint]
    rebalances: list[RebalanceOut]
    metrics: dict           # {portfolio: {...}, benchmark: {...}}
    holdings: list[dict]    # 当期持仓 [{symbol, source, name, quadrants, weight}]
    quadrant_weights: Optional[dict] = None
    corr: dict              # {labels, matrix}
    attribution: Optional[dict] = None  # 绩效归因 {summary, assets[], rebalances[]}
    method: Optional[str] = None
    available_methods: list[str] = []
    method_summaries: list[dict] = []
