import logging

import numpy as np
from fastapi import FastAPI, HTTPException

from .backtest import safe_run_backtest
from .constraints import build_constraint_output
from .contracts import (
    AllocationItem,
    BacktestRequest,
    BacktestResponse,
    PredictRequest,
    PredictResponse,
    RejectedSymbol,
)
from .data_pipeline import DataPipelineError, load_market_dataset
from .historical_ingestion import ingest_historical_market_data_to_core
from .instrument_sync import fetch_core_instrument_catalog, sync_live_instruments_to_core
from .optimizer import optimize_max_sharpe

app = FastAPI(title="EGX AI Engine", version="0.0.1")
LOGGER = logging.getLogger(__name__)
MODEL_VERSION = "mpt-egx30-v3"


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
def ingest_historical_data(years: int = 5) -> dict[str, object]:
    if years < 1 or years > 10:
        raise HTTPException(status_code=400, detail="years must be between 1 and 10")

    try:
        result = ingest_historical_market_data_to_core(years=years)
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

    symbol = raw_symbol.strip().upper()
    if not symbol:
        return None

    if ":" in symbol:
        symbol = symbol.split(":")[-1]

    if symbol.endswith(".CA"):
        return symbol[:16]

    if "." in symbol:
        symbol = symbol.split(".")[0]

    symbol = "".join(ch for ch in symbol if ch.isalnum() or ch in {"_", "-"})
    if not symbol:
        return None

    canonical = f"{symbol}.CA"
    return canonical[:16]
