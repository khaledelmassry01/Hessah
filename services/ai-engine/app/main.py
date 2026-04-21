import os
import uuid
import logging
import threading
from datetime import date

import numpy as np
from fastapi import FastAPI, HTTPException

from .backtest import safe_run_backtest
from .constraints import build_constraint_output
from .contracts import (
    AllocationItem,
    BacktestRequest,
    BacktestResponse,
    ConstraintBlock,
    PredictRequest,
    PredictResponse,
    RecommendationItem,
    RejectedSymbol,
)
from .data_pipeline import DataPipelineError, canonicalize_symbol, load_market_dataset
from .historical_ingestion import ingest_historical_market_data_to_core
from .instrument_sync import fetch_core_instrument_catalog, sync_live_instruments_to_core
from .model_training import predict_symbol_forecasts, train_models_with_retry
from .optimizer import optimize_max_sharpe
from .prediction_feedback import log_prediction_batch, reconcile_prediction_feedback

app = FastAPI(title="EGX AI Engine", version="0.0.1")
LOGGER = logging.getLogger(__name__)
MODEL_VERSION = "xgb-egx30-v1"
DEFAULT_RETRAIN_BUDGET_EGP = 500_000.0
DEFAULT_RETRAIN_LOOKBACK_BUSINESS_DAYS = 252
DEFAULT_RETRAIN_RISK_LEVEL = "HIGH"
DEFAULT_RETRAIN_TIER = "PREMIUM"
TRADING_DAYS_PER_YEAR = 252.0
FORECAST_HORIZON_DAYS = 5.0
PREVENTIVE_SELL_THRESHOLD_5D = -0.10
SMART_MAX_SECTOR_CAP = 0.30
SMART_MIN_CONFIDENCE = 0.55

TRAINING_STATE_LOCK = threading.Lock()
LATEST_TRAINING_SUMMARY: dict[str, object] = {}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "UP"}


@app.on_event("startup")
def startup_training() -> None:
    if not _resolve_env_bool("AI_AUTO_TRAIN_ON_STARTUP", True):
        LOGGER.info("ML auto-training is disabled by AI_AUTO_TRAIN_ON_STARTUP")
        return

    attempts = int(_resolve_env_float("AI_AUTO_TRAIN_ATTEMPTS", 5.0, minimum=1.0))
    delay_seconds = _resolve_env_float("AI_AUTO_TRAIN_RETRY_DELAY_SECONDS", 20.0, minimum=1.0)

    thread = threading.Thread(
        target=_run_startup_training,
        kwargs={"attempts": attempts, "delay_seconds": delay_seconds},
        daemon=True,
    )
    thread.start()


@app.post("/models/train")
def train_models_now(
    attempts: int = 3,
    delay_seconds: float = 15.0,
    target_mode: str = "RETURN_PCT",
) -> dict[str, object]:
    summary = _train_ml_models(
        reason="manual-endpoint",
        attempts=max(1, attempts),
        delay_seconds=max(1.0, float(delay_seconds)),
        target_mode=target_mode,
    )
    return {
        "status": "SUCCESS",
        "summary": summary,
    }


@app.get("/models/status")
def model_training_status() -> dict[str, object]:
    with TRAINING_STATE_LOCK:
        snapshot = dict(LATEST_TRAINING_SUMMARY)

    return {
        "status": "READY" if snapshot else "UNAVAILABLE",
        "latestTraining": snapshot,
    }


@app.post("/feedback/reconcile")
def reconcile_feedback(
    request_id: str = "feedback-reconcile",
    error_threshold: float = 0.10,
    lookback_rows: int = 30,
    trigger_mini_retrain: bool = True,
) -> dict[str, object]:
    summary = reconcile_prediction_feedback(
        error_threshold=float(error_threshold),
        lookback_rows=max(5, int(lookback_rows)),
        trigger_mini_retrain=bool(trigger_mini_retrain),
    )
    return {
        "request_id": request_id,
        "status": "SUCCESS",
        "summary": summary,
    }


@app.get("/instruments/sync")
def sync_instruments() -> dict[str, object]:
    try:
        result = sync_live_instruments_to_core()
        LOGGER.info(
            "Instrument sync completed: source=%s count=%s",
            result.get("source"),
            result.get("instrumentCount"),
        )
        return result
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Instrument sync failed")
        raise HTTPException(status_code=502, detail=f"Instrument sync failed: {exc}") from exc


@app.post("/historical/ingest")
def ingest_historical_data(
    years: int = 10,
    trigger_backtest: bool = True,
    trigger_training: bool = True,
) -> dict[str, object]:
    if years < 1 or years > 10:
        raise HTTPException(status_code=400, detail="years must be between 1 and 10")

    try:
        result = ingest_historical_market_data_to_core(years=years)

        warnings = list(result.get("warnings") or [])

        if trigger_training:
            if str(result.get("status") or "").upper() == "SUCCESS" and int(result.get("rowsSynced") or 0) > 0:
                try:
                    training_summary = _train_ml_models(reason="post-ingest", attempts=3, delay_seconds=15.0)
                    result["mlTraining"] = training_summary
                    result["modelAccuracy"] = training_summary.get("meanAccuracy", 0.0)
                except Exception as training_exc:  # noqa: BLE001
                    warnings.append(f"ML training failed: {training_exc}")
            else:
                warnings.append("ML training skipped because ingestion did not sync any market rows")

        if trigger_backtest:
            if str(result.get("status") or "").upper() == "SUCCESS" and int(result.get("rowsSynced") or 0) > 0:
                backtest_result = _run_post_ingest_backtest_cycle()
                result["trainingBacktest"] = backtest_result.model_dump(mode="json")
                result["trainingStatus"] = backtest_result.status
                result["predictedReturn"] = backtest_result.expected_return
                result["predictedVolatility"] = backtest_result.expected_volatility
                warnings.extend([f"Training/backtest: {item}" for item in backtest_result.warnings])
            else:
                warnings.append("Training/backtest skipped because ingestion did not sync any market rows")

        result["warnings"] = _dedupe_warnings([item for item in warnings if isinstance(item, str)])

        LOGGER.info(
            "Historical ingestion completed: years=%s prepared=%s synced=%s source=%s",
            years,
            result.get("rowsPrepared"),
            result.get("rowsSynced"),
            result.get("source"),
        )
        return result
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Historical ingestion failed")
        raise HTTPException(status_code=502, detail=f"Historical ingestion failed: {exc}") from exc


@app.post("/predict", response_model=PredictResponse)
def predict(payload: PredictRequest) -> PredictResponse:
    warnings: list[str] = []

    try:
        enforced_sector_cap = min(float(payload.constraints.max_sector_weight), SMART_MAX_SECTOR_CAP)
        if enforced_sector_cap < float(payload.constraints.max_sector_weight):
            warnings.append(
                f"Sector cap enforced at {SMART_MAX_SECTOR_CAP:.0%} for Smart Optimizer"
            )

        dataset = load_market_dataset(
            as_of_date=payload.as_of_date,
            max_adv30_participation=float(payload.constraints.max_adv30_participation),
            n_bars=252,
        )
        warnings.extend(dataset.warnings)

        constraint_output = build_constraint_output(
            dataset=dataset,
            budget_egp=float(payload.budget_egp),
            risk_level=payload.risk_level,
            max_sector_weight=enforced_sector_cap,
            exclude_suspended=payload.constraints.exclude_suspended,
        )
        warnings.extend(constraint_output.warnings)

        if not constraint_output.symbols:
            return PredictResponse(
                request_id=payload.request_id,
                status="FAILED",
                model_version=MODEL_VERSION,
                allocations=[],
                expected_return=0.0,
                expected_volatility=0.0,
                rejected_symbols=[
                    RejectedSymbol(symbol=_canonical_symbol(item.symbol) or item.symbol, reason=item.reason)
                    for item in constraint_output.rejected_symbols
                ],
                warnings=warnings + ["No eligible symbols after constraints"],
            )

        catalog: dict[str, object]
        try:
            catalog = fetch_core_instrument_catalog()
        except Exception as catalog_exc:  # noqa: BLE001
            warnings.append(f"Core catalog pre-flight lookup failed: {catalog_exc}")
            try:
                sync_result = sync_live_instruments_to_core()
                warnings.append(
                    "Core catalog pre-flight triggered sync: "
                    f"source={sync_result.get('source')} count={sync_result.get('instrumentCount')}"
                )
                catalog = fetch_core_instrument_catalog(force_refresh=True)
            except Exception as sync_exc:  # noqa: BLE001
                LOGGER.exception("Core catalog pre-flight and sync recovery failed")
                return PredictResponse(
                    request_id=payload.request_id,
                    status="FAILED",
                    model_version=MODEL_VERSION,
                    allocations=[],
                    expected_return=0.0,
                    expected_volatility=0.0,
                    rejected_symbols=[
                        RejectedSymbol(symbol=_canonical_symbol(item.symbol) or item.symbol, reason=item.reason)
                        for item in constraint_output.rejected_symbols
                    ],
                    warnings=warnings + [f"Core catalog validation failed: {sync_exc}"],
                )

        catalog_items = catalog.get("items") if isinstance(catalog, dict) else None
        catalog_symbols = {
            canonical
            for item in (catalog_items or [])
            if isinstance(item, dict)
            for canonical in [_canonical_symbol(item.get("symbol"))]
            if canonical is not None
        }

        eligible_symbols = list(constraint_output.symbols)
        expected_returns = constraint_output.expected_returns
        covariance = constraint_output.covariance
        bounds = list(constraint_output.bounds)
        sectors = dict(constraint_output.sectors)
        liquidity_caps_egp = dict(constraint_output.liquidity_caps_egp)
        preflight_rejected: list[RejectedSymbol] = []

        canonical_by_symbol = {
            symbol: _canonical_symbol(symbol)
            for symbol in eligible_symbols
        }
        missing_symbols = [
            symbol
            for symbol in eligible_symbols
            if canonical_by_symbol.get(symbol) is None
            or canonical_by_symbol.get(symbol) not in catalog_symbols
        ]
        if missing_symbols:
            warnings.append(
                f"{len(missing_symbols)} symbols rejected by core instrument catalog pre-flight"
            )

            for symbol in missing_symbols:
                preflight_rejected.append(
                    RejectedSymbol(
                        symbol=_canonical_symbol(symbol) or symbol,
                        reason="MISSING_CORE_INSTRUMENT",
                    )
                )

            kept_indices = [
                index
                for index, symbol in enumerate(eligible_symbols)
                if canonical_by_symbol.get(symbol) in catalog_symbols
            ]
            if not kept_indices:
                return PredictResponse(
                    request_id=payload.request_id,
                    status="FAILED",
                    model_version=MODEL_VERSION,
                    allocations=[],
                    expected_return=0.0,
                    expected_volatility=0.0,
                    rejected_symbols=[
                        RejectedSymbol(symbol=_canonical_symbol(item.symbol) or item.symbol, reason=item.reason)
                        for item in constraint_output.rejected_symbols
                    ] + preflight_rejected,
                    warnings=warnings + ["No eligible symbols after core instrument catalog pre-flight"],
                )

            eligible_symbols = [eligible_symbols[index] for index in kept_indices]
            expected_returns = expected_returns[kept_indices]
            covariance = covariance[np.ix_(kept_indices, kept_indices)]
            bounds = [bounds[index] for index in kept_indices]
            sectors = {symbol: sectors[symbol] for symbol in eligible_symbols}
            liquidity_caps_egp = {
                symbol: liquidity_caps_egp[symbol]
                for symbol in eligible_symbols
                if symbol in liquidity_caps_egp
            }

        sector_to_indices = _build_sector_index_map(eligible_symbols, sectors)

        ml_forecasts = predict_symbol_forecasts(
            as_of_date=payload.as_of_date,
            symbols=eligible_symbols,
        )
        warnings.extend(ml_forecasts.warnings)

        annualization_factor = TRADING_DAYS_PER_YEAR / FORECAST_HORIZON_DAYS
        symbol_predicted_return_5d: dict[str, float] = {}
        symbol_confidence: dict[str, float] = {}
        symbol_accuracy: dict[str, float] = {}
        expected_returns_ml_annual: list[float] = []

        for idx, symbol in enumerate(eligible_symbols):
            fallback_return_annual = float(expected_returns[idx])
            fallback_return_5d = fallback_return_annual / annualization_factor
            forecast = ml_forecasts.forecasts.get(str(symbol).upper())

            if forecast is None:
                expected_returns_ml_annual.append(fallback_return_annual)
                symbol_predicted_return_5d[symbol] = fallback_return_5d
                symbol_confidence[symbol] = 0.0
                symbol_accuracy[symbol] = float(ml_forecasts.model_accuracy)
                continue

            expected_returns_ml_annual.append(float(forecast.predicted_return_5d) * annualization_factor)
            symbol_predicted_return_5d[symbol] = float(forecast.predicted_return_5d)
            symbol_confidence[symbol] = float(forecast.confidence_score)
            symbol_accuracy[symbol] = float(forecast.model_accuracy)

        expected_returns_ml = np.array(expected_returns_ml_annual, dtype=float)

        high_confidence_symbols = [
            symbol
            for symbol in eligible_symbols
            if float(symbol_confidence.get(symbol, 0.0)) >= SMART_MIN_CONFIDENCE
        ]

        final_weights: dict[str, float] = {}
        optimization_used_fallback = False
        cash_weight = 1.0

        if not high_confidence_symbols:
            warnings.append(
                "All eligible symbols fell below the 55% confidence threshold; allocation shifted to CASH"
            )
        else:
            selected_indices = [eligible_symbols.index(symbol) for symbol in high_confidence_symbols]
            selected_returns_raw = expected_returns_ml[selected_indices]
            selected_confidence = np.array(
                [float(symbol_confidence.get(symbol, 0.0)) for symbol in high_confidence_symbols],
                dtype=float,
            )

            confidence_adjusted_returns = selected_returns_raw * np.clip(selected_confidence, 0.0, 1.0)
            selected_covariance = covariance[np.ix_(selected_indices, selected_indices)]
            selected_bounds = [bounds[idx] for idx in selected_indices]
            selected_sectors = {symbol: sectors[symbol] for symbol in high_confidence_symbols}
            selected_sector_to_indices = _build_sector_index_map(high_confidence_symbols, selected_sectors)

            optimization = optimize_max_sharpe(
                symbols=high_confidence_symbols,
                expected_returns=confidence_adjusted_returns,
                covariance=selected_covariance,
                bounds=selected_bounds,
                sector_to_indices=selected_sector_to_indices,
                max_sector_weight=enforced_sector_cap,
                risk_free_rate=0.25,
            )
            warnings.extend(optimization.warnings)
            optimization_used_fallback = optimization.used_fallback

            confidence_sized_weights = {
                symbol: float(weight) * float(symbol_confidence.get(symbol, 0.0))
                for symbol, weight in optimization.weights.items()
                if float(weight) > 0.0
            }
            final_weights, cash_weight = _apply_sector_cap_and_cash(
                raw_weights=confidence_sized_weights,
                sectors=selected_sectors,
                max_sector_weight=enforced_sector_cap,
            )

        if cash_weight > 0.0:
            warnings.append(
                f"CASH allocation {cash_weight:.2%} due to confidence thresholding and sector cap enforcement"
            )

        try:
            log_prediction_batch(
                as_of_date=payload.as_of_date,
                predictions=symbol_predicted_return_5d,
                confidence_scores=symbol_confidence,
                request_id=payload.request_id,
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Prediction audit logging failed: {exc}")

        allocations = [
            AllocationItem(
                symbol=_canonical_symbol(symbol) or symbol,
                weight=weight,
                sector=sectors[symbol],
                liquidity_cap_value_egp=round(liquidity_caps_egp.get(symbol, 0.0), 4),
                predicted_return_5d=round(float(symbol_predicted_return_5d.get(symbol, 0.0)), 8),
                confidence_score=round(float(symbol_confidence.get(symbol, 0.0)), 6),
            )
            for symbol, weight in sorted(
                final_weights.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        ]

        rejected_symbols = [
            RejectedSymbol(symbol=_canonical_symbol(item.symbol) or item.symbol, reason=item.reason)
            for item in constraint_output.rejected_symbols
        ] + preflight_rejected

        recommendations: list[RecommendationItem] = []
        predicted_portfolio_return_5d = 0.0
        weighted_confidence = 0.0
        weighted_accuracy = 0.0

        for symbol, weight in final_weights.items():
            predicted_return_5d = float(symbol_predicted_return_5d.get(symbol, 0.0))
            confidence = float(symbol_confidence.get(symbol, 0.0))
            accuracy = float(symbol_accuracy.get(symbol, ml_forecasts.model_accuracy))

            predicted_portfolio_return_5d += float(weight) * predicted_return_5d
            weighted_confidence += float(weight) * confidence
            weighted_accuracy += float(weight) * accuracy

            if predicted_return_5d <= PREVENTIVE_SELL_THRESHOLD_5D:
                recommendations.append(
                    RecommendationItem(
                        symbol=_canonical_symbol(symbol) or symbol,
                        action="PREVENTIVE_SELL",
                        reason="Model predicts >= 10% downside over next 5 trading days",
                        predicted_return_5d=round(predicted_return_5d, 8),
                        confidence_score=round(confidence, 6),
                    )
                )

        if recommendations:
            warnings.append(
                f"{len(recommendations)} symbol(s) triggered PREVENTIVE_SELL due to predicted >=10% drop"
            )

        weight_vector = np.array([float(final_weights.get(symbol, 0.0)) for symbol in eligible_symbols], dtype=float)
        expected_return_final = float(np.dot(weight_vector, expected_returns_ml)) if weight_vector.size else 0.0
        variance_final = float(np.dot(weight_vector, covariance @ weight_vector)) if weight_vector.size else 0.0
        expected_volatility_final = float(np.sqrt(max(variance_final, 0.0)))

        status = "SUCCESS"
        if rejected_symbols or optimization_used_fallback or warnings:
            status = "PARTIAL"

        return PredictResponse(
            request_id=payload.request_id,
            status=status,
            model_version=MODEL_VERSION,
            allocations=allocations,
            expected_return=round(expected_return_final, 8),
            expected_volatility=round(expected_volatility_final, 8),
            predicted_return=round(predicted_portfolio_return_5d, 8),
            confidence_score=round(float(np.clip(weighted_confidence, 0.0, 1.0)), 6),
            model_accuracy=round(float(np.clip(weighted_accuracy, 0.0, 1.0)), 6),
            recommendations=recommendations,
            rejected_symbols=rejected_symbols,
            warnings=warnings,
        )
    except DataPipelineError as exc:
        LOGGER.exception("Data pipeline failure for request %s", payload.request_id)
        return PredictResponse(
            request_id=payload.request_id,
            status="FAILED",
            model_version=MODEL_VERSION,
            allocations=[],
            expected_return=0.0,
            expected_volatility=0.0,
            rejected_symbols=[],
            warnings=[f"Data pipeline failure: {exc}"],
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Unhandled prediction failure for request %s", payload.request_id)
        return PredictResponse(
            request_id=payload.request_id,
            status="FAILED",
            model_version=MODEL_VERSION,
            allocations=[],
            expected_return=0.0,
            expected_volatility=0.0,
            rejected_symbols=[],
            warnings=[f"Unexpected error: {exc}"],
        )


@app.post("/backtest", response_model=BacktestResponse)
def backtest(payload: BacktestRequest) -> BacktestResponse:
    return safe_run_backtest(payload)


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
    positive_weights = {
        symbol: float(weight)
        for symbol, weight in raw_weights.items()
        if float(weight) > 0.0
    }
    if not positive_weights:
        return {}, 1.0

    total_weight = float(sum(positive_weights.values()))
    if total_weight <= 0.0:
        return {}, 1.0

    normalized = {
        symbol: float(weight / total_weight)
        for symbol, weight in positive_weights.items()
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
    if allocated > 0.0:
        capped = {
            symbol: float(weight)
            for symbol, weight in capped.items()
            if weight > 0.0
        }

    cash_weight += max(0.0, 1.0 - allocated - cash_weight)
    cash_weight = float(np.clip(cash_weight, 0.0, 1.0))
    return capped, cash_weight


def _canonical_symbol(raw_symbol: object) -> str | None:
    if not isinstance(raw_symbol, str):
        return None

    mapped = canonicalize_symbol(raw_symbol, allow_unmapped=False)
    if mapped is not None:
        return mapped

    return canonicalize_symbol(raw_symbol, allow_unmapped=True)


def _run_post_ingest_backtest_cycle() -> BacktestResponse:
    budget_egp = _resolve_env_float("AI_RETRAIN_BUDGET_EGP", DEFAULT_RETRAIN_BUDGET_EGP, minimum=1.0)
    lookback_days = int(
        _resolve_env_float(
            "AI_RETRAIN_LOOKBACK_BUSINESS_DAYS",
            float(DEFAULT_RETRAIN_LOOKBACK_BUSINESS_DAYS),
            minimum=10.0,
        )
    )

    risk_level = _resolve_enum_env(
        "AI_RETRAIN_RISK_LEVEL",
        {"LOW", "MEDIUM", "HIGH"},
        DEFAULT_RETRAIN_RISK_LEVEL,
    )
    tier = _resolve_enum_env(
        "AI_RETRAIN_TIER",
        {"FREE", "PREMIUM"},
        DEFAULT_RETRAIN_TIER,
    )

    backtest_payload = BacktestRequest(
        request_id=f"post-ingest-{uuid.uuid4().hex[:12]}",
        user_id="1",
        budget_egp=budget_egp,
        historical_date=_subtract_business_days(date.today(), lookback_days),
        risk_level=risk_level,
        tier=tier,
        constraints=ConstraintBlock(
            max_sector_weight=SMART_MAX_SECTOR_CAP,
            max_adv30_participation=0.05,
            exclude_suspended=True,
            allow_fractional_shares=False,
        ),
    )

    return safe_run_backtest(backtest_payload)


def _subtract_business_days(base_date: date, business_days: int) -> date:
    days = max(1, business_days)
    current = base_date
    moved = 0

    while moved < days:
        current = current.fromordinal(current.toordinal() - 1)
        if current.weekday() < 5:
            moved += 1

    return current


def _resolve_env_float(env_key: str, default_value: float, minimum: float | None = None) -> float:
    raw_value = os.getenv(env_key)
    if raw_value is None:
        resolved = float(default_value)
    else:
        try:
            resolved = float(raw_value)
        except (TypeError, ValueError):
            resolved = float(default_value)

    if minimum is not None:
        resolved = max(float(minimum), resolved)

    return resolved


def _resolve_enum_env(env_key: str, allowed_values: set[str], default_value: str) -> str:
    raw_value = os.getenv(env_key, default_value)
    normalized = str(raw_value or default_value).strip().upper()
    if normalized in allowed_values:
        return normalized
    return default_value


def _resolve_env_bool(env_key: str, default_value: bool) -> bool:
    raw_value = os.getenv(env_key)
    if raw_value is None:
        return default_value

    normalized = str(raw_value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default_value


def _run_startup_training(attempts: int, delay_seconds: float) -> None:
    try:
        _train_ml_models(
            reason="startup",
            attempts=max(1, attempts),
            delay_seconds=max(1.0, float(delay_seconds)),
            target_mode=os.getenv("AI_TARGET_MODE", "RETURN_PCT"),
        )
    except Exception:  # noqa: BLE001
        LOGGER.exception("Startup ML training failed")


def _train_ml_models(
    reason: str,
    attempts: int,
    delay_seconds: float,
    target_mode: str | None = None,
) -> dict[str, object]:
    summary = train_models_with_retry(
        attempts=max(1, attempts),
        delay_seconds=max(1.0, float(delay_seconds)),
        model_dir=os.getenv("AI_MODEL_DIR", "/app/models"),
        target_mode=target_mode or os.getenv("AI_TARGET_MODE", "RETURN_PCT"),
        horizon_days=int(_resolve_env_float("AI_FORECAST_HORIZON_DAYS", FORECAST_HORIZON_DAYS, minimum=1.0)),
        min_rows_per_symbol=int(_resolve_env_float("AI_MIN_ROWS_PER_SYMBOL", 120.0, minimum=20.0)),
    )

    summary = dict(summary)
    summary["trainingReason"] = reason

    with TRAINING_STATE_LOCK:
        LATEST_TRAINING_SUMMARY.clear()
        LATEST_TRAINING_SUMMARY.update(summary)

    LOGGER.info(
        "ML models trained: reason=%s models=%s meanAccuracy=%.4f",
        reason,
        summary.get("modelCount"),
        float(summary.get("meanAccuracy") or 0.0),
    )
    return summary


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
