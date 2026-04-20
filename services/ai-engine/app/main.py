import logging

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
from .instrument_sync import sync_live_instruments_to_core
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
                    RejectedSymbol(symbol=item.symbol, reason=item.reason)
                    for item in constraint_output.rejected_symbols
                ],
                warnings=warnings + ["No eligible symbols after constraints"],
            )

        optimization = optimize_max_sharpe(
            symbols=constraint_output.symbols,
            expected_returns=constraint_output.expected_returns,
            covariance=constraint_output.covariance,
            bounds=constraint_output.bounds,
            sector_to_indices=constraint_output.sector_to_indices,
            max_sector_weight=float(payload.constraints.max_sector_weight),
            risk_free_rate=0.25,
        )
        warnings.extend(optimization.warnings)

        allocations = [
            AllocationItem(
                symbol=symbol,
                weight=weight,
                sector=constraint_output.sectors[symbol],
                liquidity_cap_value_egp=round(constraint_output.liquidity_caps_egp[symbol], 4),
            )
            for symbol, weight in sorted(
                optimization.weights.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        ]

        rejected_symbols = [
            RejectedSymbol(symbol=item.symbol, reason=item.reason)
            for item in constraint_output.rejected_symbols
        ]

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
