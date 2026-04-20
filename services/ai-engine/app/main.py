import os
import uuid
import logging
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
    RejectedSymbol,
)
from .data_pipeline import DataPipelineError, canonicalize_symbol, load_market_dataset
from .historical_ingestion import ingest_historical_market_data_to_core
from .instrument_sync import fetch_core_instrument_catalog, sync_live_instruments_to_core
from .optimizer import optimize_max_sharpe

app = FastAPI(title="EGX AI Engine", version="0.0.1")
LOGGER = logging.getLogger(__name__)
MODEL_VERSION = "mpt-egx30-v3"
DEFAULT_RETRAIN_BUDGET_EGP = 500_000.0
DEFAULT_RETRAIN_LOOKBACK_BUSINESS_DAYS = 252
DEFAULT_RETRAIN_RISK_LEVEL = "HIGH"
DEFAULT_RETRAIN_TIER = "PREMIUM"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "UP"}


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
def ingest_historical_data(years: int = 10, trigger_backtest: bool = True) -> dict[str, object]:
    if years < 1 or years > 10:
        raise HTTPException(status_code=400, detail="years must be between 1 and 10")

    try:
        result = ingest_historical_market_data_to_core(years=years)

        warnings = list(result.get("warnings") or [])
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
            max_sector_weight=float(payload.constraints.max_sector_weight),
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

        optimization = optimize_max_sharpe(
            symbols=eligible_symbols,
            expected_returns=expected_returns,
            covariance=covariance,
            bounds=bounds,
            sector_to_indices=sector_to_indices,
            max_sector_weight=float(payload.constraints.max_sector_weight),
            risk_free_rate=0.25,
        )
        warnings.extend(optimization.warnings)

        allocations = [
            AllocationItem(
                symbol=_canonical_symbol(symbol) or symbol,
                weight=weight,
                sector=sectors[symbol],
                liquidity_cap_value_egp=round(liquidity_caps_egp.get(symbol, 0.0), 4),
            )
            for symbol, weight in sorted(
                optimization.weights.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        ]

        rejected_symbols = [
            RejectedSymbol(symbol=_canonical_symbol(item.symbol) or item.symbol, reason=item.reason)
            for item in constraint_output.rejected_symbols
        ] + preflight_rejected

        status = "SUCCESS"
        if rejected_symbols or optimization.used_fallback or warnings:
            status = "PARTIAL"

        return PredictResponse(
            request_id=payload.request_id,
            status=status,
            model_version=MODEL_VERSION,
            allocations=allocations,
            expected_return=round(optimization.expected_return, 8),
            expected_volatility=round(optimization.expected_volatility, 8),
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
            max_sector_weight=0.40,
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
