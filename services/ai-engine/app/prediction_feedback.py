from __future__ import annotations

from datetime import date, timedelta
import re
from typing import Any

import pandas as pd

from .feature_engineering import (
    MysqlSettings,
    load_historical_market_data,
    open_mysql_connection,
)
from .model_training import train_models_with_retry

PREDICTION_HORIZON_DAYS = 5
DEFAULT_LOOKBACK_ROWS = 30


def _normalize_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        return ""

    if ":" in normalized:
        normalized = normalized.split(":")[-1]

    normalized = re.sub(r"[^A-Z0-9._-]", "", normalized)
    if not normalized:
        return ""

    if normalized.endswith(".CA"):
        return normalized[:16]

    if "." in normalized:
        normalized = normalized.split(".", maxsplit=1)[0]

    normalized = re.sub(r"[^A-Z0-9_-]", "", normalized)
    if not normalized:
        return ""

    return f"{normalized}.CA"[:16]


def _ensure_daily_ai_signals_table(connection) -> None:
    """Ensure daily_ai_signals table exists."""
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_ai_signals (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                symbol VARCHAR(16) NOT NULL,
                stock_id BIGINT NULL,
                signal_date DATE NOT NULL,
                action VARCHAR(20) NOT NULL,
                confidence_score DECIMAL(6,4) NULL,
                predicted_return_5d DECIMAL(10,6) NULL,
                model_version VARCHAR(64) NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_daily_ai_signals_symbol_date (symbol, signal_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        connection.commit()
    finally:
        cursor.close()


def save_predictions_to_daily_signals(
    signal_date: date,
    recommendations: list[dict],
    model_version: str = "xgb-egx30-v1",
    settings: MysqlSettings | None = None,
) -> int:
    """Save AI predictions to daily_ai_signals table for MarketWatch.
    
    Args:
        signal_date: The date for the signals
        recommendations: List of recommendation dicts with 'symbol', 'action', 'confidence_score', and optional 'predicted_return_5d'
        model_version: Model version string
        settings: MySQL connection settings
        
    Returns:
        Number of signals saved
    """
    if not recommendations:
        return 0

    from datetime import datetime

    connection = open_mysql_connection(settings=settings)
    try:
        _ensure_daily_ai_signals_table(connection)

        rows = []
        now = datetime.now()
        for rec in recommendations:
            symbol = rec.get("symbol", "").upper().strip()
            if not symbol:
                continue
            # Determine action from recommendation
            action = rec.get("action", "HOLD")
            confidence = rec.get("confidence_score", 0.0)
            predicted_return_5d = rec.get("predicted_return_5d")
            
            rows.append(
                (
                    symbol,
                    signal_date,
                    action,
                    float(confidence),
                    float(predicted_return_5d) if predicted_return_5d is not None else None,
                    model_version,
                    now,
                    now,
                )
            )

        if not rows:
            return 0

        cursor = connection.cursor()
        try:
            cursor.executemany(
                """
                INSERT INTO daily_ai_signals (
                    symbol,
                    signal_date,
                    action,
                    confidence_score,
                    predicted_return_5d,
                    model_version,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    action = VALUES(action),
                    confidence_score = VALUES(confidence_score),
                    predicted_return_5d = VALUES(predicted_return_5d),
                    model_version = VALUES(model_version),
                    updated_at = VALUES(updated_at)
                """,
                rows,
            )
            connection.commit()
        finally:
            cursor.close()

        return len(rows)
    finally:
        connection.close()


def _ensure_prediction_audit_table(connection) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS prediction_audit (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                as_of_date DATE NOT NULL,
                symbol VARCHAR(16) NOT NULL,
                request_id VARCHAR(128) NULL,
                predicted_return_5d DOUBLE NOT NULL,
                confidence_score DOUBLE NULL,
                actual_return_5d DOUBLE NULL,
                error_abs DOUBLE NULL,
                reconciled_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_prediction_audit_asof_symbol_request (as_of_date, symbol, request_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        connection.commit()
    finally:
        cursor.close()


def log_prediction_batch(
    as_of_date: date,
    predictions: dict[str, float],
    confidence_scores: dict[str, float] | None = None,
    request_id: str | None = None,
    settings: MysqlSettings | None = None,
) -> int:
    if not predictions:
        return 0

    connection = open_mysql_connection(settings=settings)
    try:
        _ensure_prediction_audit_table(connection)

        rows = []
        for symbol, predicted in predictions.items():
            normalized_symbol = _normalize_symbol(symbol)
            if not normalized_symbol:
                continue
            rows.append(
                (
                    as_of_date,
                    normalized_symbol,
                    (request_id or "predict-request")[:128],
                    float(predicted),
                    float((confidence_scores or {}).get(symbol, 0.0)),
                )
            )

        if not rows:
            return 0

        cursor = connection.cursor()
        try:
            cursor.executemany(
                """
                INSERT INTO prediction_audit (
                    as_of_date,
                    symbol,
                    request_id,
                    predicted_return_5d,
                    confidence_score
                )
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    predicted_return_5d = VALUES(predicted_return_5d),
                    confidence_score = VALUES(confidence_score),
                    updated_at = CURRENT_TIMESTAMP
                """,
                rows,
            )
            connection.commit()
        finally:
            cursor.close()

        return len(rows)
    finally:
        connection.close()


def _build_actual_return_lookup(frame: pd.DataFrame) -> dict[tuple[str, date], float]:
    lookup: dict[tuple[str, date], float] = {}
    if frame.empty:
        return lookup

    local = frame.sort_values(["symbol", "trade_date"]).copy()
    local["future_close"] = local.groupby("symbol")["close_price"].shift(-PREDICTION_HORIZON_DAYS)
    local["actual_return_5d"] = (local["future_close"] / local["close_price"]) - 1.0

    for row in local.itertuples(index=False):
        trade_date = pd.Timestamp(getattr(row, "trade_date")).date()
        symbol = str(getattr(row, "symbol"))
        actual = getattr(row, "actual_return_5d")
        if pd.isna(actual):
            continue
        lookup[(symbol, trade_date)] = float(actual)

    return lookup


def reconcile_prediction_feedback(
    error_threshold: float = 0.10,
    lookback_rows: int = DEFAULT_LOOKBACK_ROWS,
    trigger_mini_retrain: bool = True,
    settings: MysqlSettings | None = None,
) -> dict[str, Any]:
    connection = open_mysql_connection(settings=settings)
    try:
        _ensure_prediction_audit_table(connection)
        pending = pd.read_sql(
            sql=(
                "SELECT id, as_of_date, symbol, predicted_return_5d "
                "FROM prediction_audit "
                "WHERE actual_return_5d IS NULL "
                "ORDER BY as_of_date ASC"
            ),
            con=connection,
        )
    finally:
        connection.close()

    if pending.empty:
        return {
            "pendingRows": 0,
            "reconciledRows": 0,
            "flaggedSymbols": [],
            "retrainedSymbols": [],
        }

    pending["as_of_date"] = pd.to_datetime(pending["as_of_date"], errors="coerce")
    pending = pending.dropna(subset=["as_of_date", "symbol"])
    pending["symbol"] = pending["symbol"].map(lambda item: _normalize_symbol(str(item)))
    pending = pending.loc[pending["symbol"].astype(bool)].copy()

    min_date = pd.Timestamp(pending["as_of_date"].min()).date() - timedelta(days=30)
    symbols = sorted(set(str(item) for item in pending["symbol"].tolist()))

    history = load_historical_market_data(
        symbols=symbols,
        start_date=min_date,
    )
    actual_lookup = _build_actual_return_lookup(history)

    updates: list[tuple[float, float, int]] = []
    for row in pending.itertuples(index=False):
        trade_date = pd.Timestamp(getattr(row, "as_of_date")).date()
        symbol = str(getattr(row, "symbol"))
        predicted = float(getattr(row, "predicted_return_5d"))
        actual = actual_lookup.get((symbol, trade_date))
        if actual is None:
            continue
        error_abs = abs(float(actual) - predicted)
        updates.append((float(actual), float(error_abs), int(getattr(row, "id"))))

    if updates:
        connection = open_mysql_connection(settings=settings)
        try:
            cursor = connection.cursor()
            try:
                cursor.executemany(
                    """
                    UPDATE prediction_audit
                    SET actual_return_5d = %s,
                        error_abs = %s,
                        reconciled_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    updates,
                )
                connection.commit()
            finally:
                cursor.close()
        finally:
            connection.close()

    connection = open_mysql_connection(settings=settings)
    try:
        scored = pd.read_sql(
            sql=(
                "SELECT symbol, as_of_date, error_abs "
                "FROM prediction_audit "
                "WHERE error_abs IS NOT NULL"
            ),
            con=connection,
        )
    finally:
        connection.close()

    flagged_symbols: list[str] = []
    if not scored.empty:
        scored["as_of_date"] = pd.to_datetime(scored["as_of_date"], errors="coerce")
        scored = scored.dropna(subset=["as_of_date", "symbol", "error_abs"])
        scored = scored.sort_values(["symbol", "as_of_date"], ascending=[True, False])
        scored["row_num"] = scored.groupby("symbol").cumcount() + 1
        recent = scored.loc[scored["row_num"] <= max(5, int(lookback_rows))].copy()
        cumulative_error = recent.groupby("symbol", as_index=False)["error_abs"].sum()
        flagged_symbols = sorted(
            cumulative_error.loc[
                cumulative_error["error_abs"] > float(error_threshold),
                "symbol",
            ].astype(str).tolist()
        )

    retrained_symbols: list[str] = []
    if trigger_mini_retrain and flagged_symbols:
        train_models_with_retry(
            attempts=1,
            delay_seconds=1.0,
            symbols=flagged_symbols,
            target_mode="RETURN_PCT",
            horizon_days=PREDICTION_HORIZON_DAYS,
            min_rows_per_symbol=80,
            use_recency_weighting=True,
        )
        retrained_symbols = flagged_symbols

    return {
        "pendingRows": int(len(pending)),
        "reconciledRows": int(len(updates)),
        "flaggedSymbols": flagged_symbols,
        "retrainedSymbols": retrained_symbols,
        "errorThreshold": float(error_threshold),
        "lookbackRows": int(max(5, int(lookback_rows))),
    }
