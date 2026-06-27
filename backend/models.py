"""
models.py
=========
Pydantic request/response schemas for the API. Keeping them here means the
endpoint signatures in main.py stay short and self-documenting.
"""

from __future__ import annotations
from pydantic import BaseModel, Field, field_validator


ALLOWED_TF = {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}


class TradingConfig(BaseModel):
    """Editable trading parameters (the UI config panel saves this)."""
    symbol_universe: list[str] = Field(min_length=1)
    timeframe: str
    leverage: int = Field(ge=1, le=50)
    position_size_pct: float = Field(gt=0, le=100)
    stop_loss_pct: float = Field(gt=0, le=100)
    take_profit_pct: float = Field(gt=0, le=100)
    max_drawdown_pct: float = Field(gt=0, le=100)
    # Automation fields (optional so older clients still validate).
    scan_timeframes: list[str] = Field(default_factory=lambda: ["15m", "1h", "4h", "1d"])
    scan_interval_min: int = Field(default=30, ge=1, le=1440)
    scan_enabled: bool = True
    auto_trade: bool = False
    auto_trade_confidence: float = Field(default=65, ge=0, le=100)
    auto_analyze: bool = False
    daily_loss_limit_pct: float = Field(default=0, ge=0, le=100)
    min_minutes_between_trades: float = Field(default=0, ge=0, le=1440)

    @field_validator("timeframe")
    @classmethod
    def _tf(cls, v: str) -> str:
        if v not in ALLOWED_TF:
            raise ValueError(f"timeframe must be one of {sorted(ALLOWED_TF)}")
        return v

    @field_validator("scan_timeframes")
    @classmethod
    def _stf(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("scan_timeframes must have at least one timeframe")
        bad = [x for x in v if x not in ALLOWED_TF]
        if bad:
            raise ValueError(f"invalid timeframes: {bad}")
        return v


class AutomationConfig(BaseModel):
    """The Automation tab posts just these (a focused subset of the config)."""
    scan_enabled: bool
    auto_trade: bool
    auto_trade_confidence: float = Field(ge=0, le=100)
    scan_interval_min: int = Field(ge=1, le=1440)
    scan_timeframes: list[str] = Field(min_length=1)
    auto_analyze: bool = False
    daily_loss_limit_pct: float = Field(default=0, ge=0, le=100)
    min_minutes_between_trades: float = Field(default=0, ge=0, le=1440)

    @field_validator("scan_timeframes")
    @classmethod
    def _stf(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x not in ALLOWED_TF]
        if bad:
            raise ValueError(f"invalid timeframes: {bad}")
        return v


class GoLiveRequest(BaseModel):
    """Switching to mainnet. confirmation must equal 'GO LIVE'."""
    confirmation: str


class DecisionAction(BaseModel):
    """Approve or reject a pending decision file."""
    filename: str
    approve: bool
