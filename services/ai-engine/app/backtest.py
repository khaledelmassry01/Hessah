from __future__ import annotations

from datetime import date
from math import floor
from typing import Any

import numpy as np

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
SMART_MAX_SECTOR_CAP = 0.40
SMART_MIN_CONFIDENCE = 0.50


def run_backtest(payload: BacktestRequest) -> BacktestResponse:
    warnings: list[str] = []
    # FIXED: Use request's max_sector_weight directly without hardcoded ceiling
    enforced_sector_cap = float(payload.constraints.max_sector_weight)
    if enforced_sector_cap > 0.5:
        warnings.append(f"Sector cap set to {enforced_sector_cap:.0%} (high concentration risk)")

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
        max_sector_weight=enforced_sector_cap,
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

    expected_returns = np.array(constraint_output.expected_returns, dtype=float)
    absolute_signal = np.abs(expected_returns)
    scale = float(max(np.max(absolute_signal), 1e-9))
    confidence_scores = np.clip(0.45 + (0.55 * (absolute_signal / scale)), 0.0, 1.0)

    high_confidence_indices = [
        idx
        for idx, score in enumerate(confidence_scores)
        if float(score) >= SMART_MIN_CONFIDENCE
    ]

    final_weights: dict[str, float] = {}
    optimization_used_fallback = False
    cash_weight = 1.0

    if not high_confidence_indices:
        warnings.append("All symbols fell below confidence threshold; backtest capital held in CASH")
    else:
        selected_symbols = [constraint_output.symbols[idx] for idx in high_confidence_indices]
        selected_returns = expected_returns[high_confidence_indices] * confidence_scores[high_confidence_indices]
        selected_covariance = constraint_output.covariance[np.ix_(high_confidence_indices, high_confidence_indices)]
        selected_bounds = [constraint_output.bounds[idx] for idx in high_confidence_indices]
        selected_sectors = {
            symbol: constraint_output.sectors[symbol]
            for symbol in selected_symbols
        }
        selected_sector_to_indices = _build_sector_index_map(selected_symbols, selected_sectors)

        optimization = optimize_max_sharpe(
            symbols=selected_symbols,
            expected_returns=selected_returns,
            covariance=selected_covariance,
            bounds=selected_bounds,
            sector_to_indices=selected_sector_to_indices,
            max_sector_weight=enforced_sector_cap,
            risk_free_rate=adaptive_params.risk_free_rate,
            covariance_shrinkage=adaptive_params.covariance_shrinkage,
        )
        warnings.extend(optimization.warnings)
        optimization_used_fallback = optimization.used_fallback

        confidence_by_symbol = {
            symbol: float(confidence_scores[idx])
            for symbol, idx in zip(selected_symbols, high_confidence_indices)
        }
        confidence_sized = {
            symbol: float(weight) * float(confidence_by_symbol.get(symbol, 0.0))
            for symbol, weight in optimization.weights.items()
            if float(weight) > 0.0
        }
        final_weights, cash_weight = _apply_sector_cap_and_cash(
            raw_weights=confidence_sized,
            sectors=selected_sectors,
            max_sector_weight=enforced_sector_cap,
        )

    if cash_weight > 0.0:
        warnings.append(f"Backtest CASH allocation={cash_weight:.2%} from confidence/sector controls")

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

    for symbol, weight in sorted(final_weights.items(), key=lambda item: item[1], reverse=True):
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
    confidence_cash = budget * float(cash_weight)
    residual_cash = max(residual_cash, confidence_cash)
    original_value = budget
    current_value = current_value_positions + residual_cash
    roi_pct = ((current_value - original_value) / original_value) * 100.0 if original_value > 0 else 0.0
    weight_vector = np.array([float(final_weights.get(symbol, 0.0)) for symbol in constraint_output.symbols], dtype=float)
    predicted_return_realized = float(np.dot(weight_vector, expected_returns)) if weight_vector.size else 0.0
    variance_realized = float(np.dot(weight_vector, constraint_output.covariance @ weight_vector)) if weight_vector.size else 0.0
    expected_volatility = float(np.sqrt(max(variance_realized, 0.0)))
    actual_return_realized = ((current_value - original_value) / original_value) if original_value > 0 else 0.0
    prediction_error = actual_return_realized - predicted_return_realized

    status = "SUCCESS"
    rejected_symbols = [
        RejectedSymbol(symbol=item.symbol, reason=item.reason)
        for item in constraint_output.rejected_symbols
    ]
    if rejected_symbols or optimization_used_fallback or warnings:
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
        expected_return=round(float(predicted_return_realized), 8),
        expected_volatility=round(float(expected_volatility), 8),
        historical_allocations=historical_allocations,
        rejected_symbols=rejected_symbols,
        warnings=_dedupe_warnings(warnings),
    )


def _build_sector_index_map(symbols: list[str], sectors: dict[str, str]) -> dict[str, list[int]]:
    mapping: dict[str, list[int]] = {}
    for idx, symbol in enumerate(symbols):
        mapping.setdefault(sectors[symbol], []).append(idx)
    return mapping


def _apply_sector_cap_and_cash(
    raw_weights: dict[str, float],
    sectors: dict[str, str],
    max_sector_weight: float,
) -> tuple[dict[str, float], float]:
    positive = {
        symbol: float(weight)
        for symbol, weight in raw_weights.items()
        if float(weight) > 0.0
    }
    if not positive:
        return {}, 1.0

    total = float(sum(positive.values()))
    if total <= 0.0:
        return {}, 1.0

    normalized = {
        symbol: float(weight / total)
        for symbol, weight in positive.items()
    }

    capped: dict[str, float] = {}
    sector_used: dict[str, float] = {}
    cash_weight = 0.0

    for symbol, weight in sorted(normalized.items(), key=lambda item: item[1], reverse=True):
        sector = sectors.get(symbol, "UNMAPPED")
        used = sector_used.get(sector, 0.0)
        room = max(0.0, float(max_sector_weight) - used)
        accepted = min(weight, room)

        if accepted > 0.0:
            capped[symbol] = accepted
            sector_used[sector] = used + accepted

        cash_weight += max(0.0, weight - accepted)

    allocated = float(sum(capped.values()))
    cash_weight += max(0.0, 1.0 - allocated - cash_weight)
    cash_weight = float(np.clip(cash_weight, 0.0, 1.0))
    return capped, cash_weight


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
