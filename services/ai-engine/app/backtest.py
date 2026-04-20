from __future__ import annotations

from datetime import date
from math import floor
from typing import Any

from .constraints import build_constraint_output
from .contracts import (
    BacktestAllocationItem,
    BacktestRequest,
    BacktestResponse,
    RejectedSymbol,
)
from .data_pipeline import DataPipelineError, load_market_dataset
from .learning_feedback import log_model_performance, resolve_adaptive_parameters
from .optimizer import optimize_max_sharpe

MODEL_VERSION = "mpt-egx30-backtest-v2-learning"
FORWARD_HORIZON_DAYS = 90


def run_backtest(payload: BacktestRequest) -> BacktestResponse:
    warnings: list[str] = []

    adaptive_params, adaptive_warnings = resolve_adaptive_parameters(payload.risk_level)
    warnings.extend(adaptive_warnings)
    warnings.append(
        "Adaptive parameters source="
        f"{adaptive_params.source} sampleSize={adaptive_params.sample_size}"
    )

    historical_dataset = load_market_dataset(
        as_of_date=payload.historical_date,
        max_adv30_participation=float(payload.constraints.max_adv30_participation),
        n_bars=252,
    )
    warnings.extend(historical_dataset.warnings)

    constraint_output = build_constraint_output(
        dataset=historical_dataset,
        budget_egp=float(payload.budget_egp),
        risk_level=payload.risk_level,
        max_sector_weight=float(payload.constraints.max_sector_weight),
        exclude_suspended=payload.constraints.exclude_suspended,
    )
    warnings.extend(constraint_output.warnings)

    if not constraint_output.symbols:
        return BacktestResponse(
            request_id=payload.request_id,
            status="FAILED",
            model_version=MODEL_VERSION,
            historical_date=payload.historical_date,
            original_value_egp=round(float(payload.budget_egp), 4),
            current_value_egp=round(float(payload.budget_egp), 4),
            roi_pct=0.0,
            expected_return=0.0,
            expected_volatility=0.0,
            historical_allocations=[],
            rejected_symbols=[
                RejectedSymbol(symbol=item.symbol, reason=item.reason)
                for item in constraint_output.rejected_symbols
            ],
            warnings=_dedupe_warnings(warnings + ["No eligible symbols after historical constraints"]),
        )

    optimization = optimize_max_sharpe(
        symbols=constraint_output.symbols,
        expected_returns=constraint_output.expected_returns,
        covariance=constraint_output.covariance,
        bounds=constraint_output.bounds,
        sector_to_indices=constraint_output.sector_to_indices,
        max_sector_weight=float(payload.constraints.max_sector_weight),
        risk_free_rate=adaptive_params.risk_free_rate,
        covariance_shrinkage=adaptive_params.covariance_shrinkage,
    )
    warnings.extend(optimization.warnings)

    evaluation_date = _add_business_days(payload.historical_date, FORWARD_HORIZON_DAYS)
    current_dataset = load_market_dataset(
        as_of_date=evaluation_date,
        max_adv30_participation=float(payload.constraints.max_adv30_participation),
        n_bars=252,
    )
    warnings.extend(current_dataset.warnings)

    budget = float(payload.budget_egp)
    historical_allocations: list[BacktestAllocationItem] = []
    invested_value = 0.0
    current_value_positions = 0.0

    for symbol, weight in sorted(optimization.weights.items(), key=lambda item: item[1], reverse=True):
        historical_snapshot = historical_dataset.snapshots[symbol]
        current_snapshot = current_dataset.snapshots.get(symbol, historical_snapshot)

        allocated_value = budget * float(weight)
        historical_price = float(historical_snapshot.current_price)
        current_price = float(current_snapshot.current_price)

        if payload.constraints.allow_fractional_shares:
            shares = allocated_value / historical_price
        else:
            shares = float(floor(allocated_value / historical_price))

        position_value_historical = shares * historical_price
        position_value_current = shares * current_price

        invested_value += position_value_historical
        current_value_positions += position_value_current

        historical_allocations.append(
            BacktestAllocationItem(
                symbol=symbol,
                sector=constraint_output.sectors[symbol],
                weight=round(float(weight), 8),
                historical_price=round(historical_price, 4),
                current_price=round(current_price, 4),
                shares=round(shares, 8),
                allocated_value_egp=round(position_value_historical, 4),
                current_value_egp=round(position_value_current, 4),
            )
        )

    residual_cash = max(0.0, budget - invested_value)
    original_value = budget
    current_value = current_value_positions + residual_cash
    roi_pct = ((current_value - original_value) / original_value) * 100.0 if original_value > 0 else 0.0
    predicted_return_realized = float(optimization.expected_return)
    actual_return_realized = ((current_value - original_value) / original_value) if original_value > 0 else 0.0
    prediction_error = actual_return_realized - predicted_return_realized

    status = "SUCCESS"
    rejected_symbols = [
        RejectedSymbol(symbol=item.symbol, reason=item.reason)
        for item in constraint_output.rejected_symbols
    ]
    if rejected_symbols or optimization.used_fallback or warnings:
        status = "PARTIAL"

    warnings.extend(
        _persist_feedback_event(
            payload=payload,
            status=status,
            predicted_return=predicted_return_realized,
            actual_return=actual_return_realized,
            prediction_error=prediction_error,
            risk_free_rate=adaptive_params.risk_free_rate,
            covariance_shrinkage=adaptive_params.covariance_shrinkage,
            evaluation_date=evaluation_date,
        )
    )

    return BacktestResponse(
        request_id=payload.request_id,
        status=status,
        model_version=MODEL_VERSION,
        historical_date=payload.historical_date,
        original_value_egp=round(original_value, 4),
        current_value_egp=round(current_value, 4),
        roi_pct=round(roi_pct, 6),
        expected_return=round(float(optimization.expected_return), 8),
        expected_volatility=round(float(optimization.expected_volatility), 8),
        historical_allocations=historical_allocations,
        rejected_symbols=rejected_symbols,
        warnings=_dedupe_warnings(warnings),
    )


def _persist_feedback_event(
    payload: BacktestRequest,
    status: str,
    predicted_return: float,
    actual_return: float,
    prediction_error: float,
    risk_free_rate: float,
    covariance_shrinkage: float,
    evaluation_date: date,
) -> list[str]:
    event: dict[str, Any] = {
        "requestId": payload.request_id,
        "userId": int(payload.user_id) if str(payload.user_id).isdigit() else None,
        "riskLevel": payload.risk_level,
        "modelVersion": MODEL_VERSION,
        "historicalDate": payload.historical_date.isoformat(),
        "evaluationDate": evaluation_date.isoformat(),
        "horizonDays": FORWARD_HORIZON_DAYS,
        "budgetEgp": round(float(payload.budget_egp), 4),
        "predictedReturn": round(predicted_return, 8),
        "actualReturn": round(actual_return, 8),
        "predictionError": round(prediction_error, 8),
        "riskFreeRate": round(risk_free_rate, 6),
        "covarianceShrinkage": round(covariance_shrinkage, 6),
        "runStatus": status,
    }

    return log_model_performance(event)


def _add_business_days(base_date: date, business_days: int) -> date:
    if business_days <= 0:
        return base_date

    current = base_date
    added = 0
    while added < business_days:
        current = current.fromordinal(current.toordinal() + 1)
        if current.weekday() < 5:
            added += 1
    return current


def _dedupe_warnings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []

    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue

        seen.add(normalized)
        deduped.append(normalized)

    return deduped


def safe_run_backtest(payload: BacktestRequest) -> BacktestResponse:
    try:
        return run_backtest(payload)
    except DataPipelineError as exc:
        return BacktestResponse(
            request_id=payload.request_id,
            status="FAILED",
            model_version=MODEL_VERSION,
            historical_date=payload.historical_date,
            original_value_egp=round(float(payload.budget_egp), 4),
            current_value_egp=round(float(payload.budget_egp), 4),
            roi_pct=0.0,
            expected_return=0.0,
            expected_volatility=0.0,
            historical_allocations=[],
            rejected_symbols=[],
            warnings=[f"Backtest data pipeline failure: {exc}"],
        )
