from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class StrategyType(str, Enum):
    DCA = "dca"
    MA_BAND = "ma_band"
    DYNAMIC = "dynamic"
    QUALITY_GRID = "quality_grid"


class BacktestRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    strategy: StrategyType
    start_date: date
    end_date: date
    initial_cash: float = Field(default=100_000, ge=0)
    monthly_contribution: float = Field(default=5_000, ge=0)
    contribution_day: int = Field(default=1, ge=1, le=28)
    ma_window: int = Field(default=120, ge=2, le=3000)
    lower_threshold: float = Field(default=-0.05, ge=-0.9, le=0)
    upper_threshold: float = Field(default=0.05, ge=0, le=2)
    extra_buy_amount: float = Field(default=10_000, ge=0)
    sell_ratio: float = Field(default=0.2, ge=0, le=1)
    allow_margin: bool = True
    rebalance_tolerance: float = Field(default=0.01, ge=0, le=0.5)

    # Quality Grid / 质量过滤逐笔网格
    max_strategy_cash: float = Field(default=1_000_000, gt=0)
    base_cash: float = Field(default=20_000, gt=0)
    quality_confirmed: bool = True
    lookback_days: int = Field(default=360, ge=2, le=3000)
    entry_drawdown_pct: float = Field(default=0.30, ge=0, lt=1)
    ma_discount_pct: float = Field(default=0.15, ge=0, lt=1)
    entry_condition_mode: Literal["all", "any"] = "all"
    grid_drop_pcts: list[float] = Field(default_factory=lambda: [0.05, 0.10, 0.15, 0.20], min_length=4, max_length=4)
    grid_cash_multipliers: list[float] = Field(default_factory=lambda: [1.0, 2.0, 2.0, 2.0], min_length=4, max_length=4)
    lot_take_profit_pct: float = Field(default=0.05, gt=0, lt=5)
    basket_take_profit_enabled: bool = True
    basket_take_profit_pct: float = Field(default=0.10, gt=0, lt=5)
    reentry_drop_pct: float = Field(default=0.05, ge=0, lt=1)
    commission_rate: float = Field(default=0.0003, ge=0, lt=0.1)
    min_commission: float = Field(default=5.0, ge=0)
    sell_tax_rate: float = Field(default=0.001, ge=0, lt=0.1)
    slippage_pct: float = Field(default=0.0005, ge=0, lt=0.1)
    enforce_a_share_board_lot: bool = True
    allow_fractional_etf: bool = False
    execution_mode: Literal["next_open"] = "next_open"

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_quality_grid(self):
        if any(x <= 0 or x >= 1 for x in self.grid_drop_pcts):
            raise ValueError("四层补仓跌幅必须在 0 和 1 之间")
        if self.grid_drop_pcts != sorted(self.grid_drop_pcts) or len(set(self.grid_drop_pcts)) != 4:
            raise ValueError("四层补仓跌幅必须严格递增")
        if any(x <= 0 for x in self.grid_cash_multipliers):
            raise ValueError("补仓金额倍数必须大于 0")
        if self.base_cash > self.max_strategy_cash:
            raise ValueError("首仓金额不能超过策略资金池上限")
        return self


class TargetEntryRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    lookback_days: int = Field(default=360, ge=2, le=3000)
    ma_window: int = Field(default=120, ge=2, le=3000)
    entry_drawdown_pct: float = Field(default=0.30, ge=0, lt=1)
    ma_discount_pct: float = Field(default=0.15, ge=0, lt=1)
    as_of_date: date | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

class OptimizationRequest(BacktestRequest):
    strategy: StrategyType = StrategyType.MA_BAND
    ma_windows: list[int] = [60, 120, 180, 200]
    thresholds: list[float] = [0.05, 0.10, 0.15]


class Trade(BaseModel):
    date: date
    side: str
    price: float
    quantity: float
    notional: float
    reason: str
    status: str = "FILLED"
    signal_date: date | None = None
    lot_id: str | None = None
    round_no: int | None = None
    layer_no: int | None = None
    commission: float = 0.0
    tax: float = 0.0
    cash_flow: float = 0.0
    realized_pnl: float | None = None


class LotRecord(BaseModel):
    lot_id: str
    round_no: int
    layer_no: int
    buy_date: date
    buy_price: float
    quantity: float
    cost: float
    buy_commission: float = 0.0
    status: str
    sell_date: date | None = None
    sell_price: float | None = None
    sell_commission: float = 0.0
    sell_tax: float = 0.0
    realized_pnl: float | None = None
    return_pct: float | None = None
    exit_reason: str | None = None
    holding_days: int = 0
