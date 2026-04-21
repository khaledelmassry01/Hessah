from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConstraintBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_sector_weight: float = Field(default=0.40, ge=0.0, le=1.0)
    max_adv30_participation: float = Field(default=0.05, ge=0.0, le=1.0)
    exclude_suspended: bool = True
    allow_fractional_shares: bool = False


class PredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    user_id: str
    as_of_date: date
    budget_egp: float = Field(gt=0.0)
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    tier: Literal["FREE", "PREMIUM"]
    constraints: ConstraintBlock


class AllocationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    weight: float = Field(ge=0.0, le=1.0)
    sector: str
    liquidity_cap_value_egp: float = Field(ge=0.0)


class RejectedSymbol(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    reason: str


class RecommendationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    action: Literal["PREVENTIVE_SELL", "SELL", "HOLD", "BUY"]
    reason: str
    predicted_return_5d: float
    confidence_score: float = Field(ge=0.0, le=1.0)


class PredictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    request_id: str
    status: Literal["SUCCESS", "PARTIAL", "FAILED"]
    model_version: str
    allocations: list[AllocationItem]
    expected_return: float
    expected_volatility: float
    predicted_return: float = 0.0
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    model_accuracy: float = Field(default=0.0, ge=0.0, le=1.0)
    recommendations: list[RecommendationItem] = Field(default_factory=list)
    rejected_symbols: list[RejectedSymbol] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    user_id: str
    budget_egp: float = Field(gt=0.0)
    historical_date: date
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    tier: Literal["FREE", "PREMIUM"]
    constraints: ConstraintBlock


class BacktestAllocationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    sector: str
    weight: float = Field(ge=0.0, le=1.0)
    historical_price: float = Field(gt=0.0)
    current_price: float = Field(gt=0.0)
    shares: float = Field(ge=0.0)
    allocated_value_egp: float = Field(ge=0.0)
    current_value_egp: float = Field(ge=0.0)


class BacktestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    request_id: str
    status: Literal["SUCCESS", "PARTIAL", "FAILED"]
    model_version: str
    historical_date: date
    original_value_egp: float
    current_value_egp: float
    roi_pct: float
    expected_return: float
    expected_volatility: float
    historical_allocations: list[BacktestAllocationItem]
    rejected_symbols: list[RejectedSymbol] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
