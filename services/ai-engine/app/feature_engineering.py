from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass
from datetime import date
from typing import Any

import mysql.connector
import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)

DEFAULT_DB_HOST = "mysql-db"
DEFAULT_DB_PORT = 3306
DEFAULT_DB_NAME = "egx_portfolio"
DEFAULT_DB_USER = "egx_app_user"
DEFAULT_DB_PASSWORD = "EGX_App_7wN!9Qx2#M4Lz8"
DEFAULT_LOOKBACK_START = date(2016, 1, 1)

FEATURE_COLUMNS = [
    "close_price",
    "daily_return",
    "ema_20",
    "ema_50",
    "macd",
    "macd_signal",
    "macd_hist",
    "rsi_14",
    "volume",
]


@dataclass(frozen=True)
class MysqlSettings:
    host: str
    port: int
    user: str
    password: str
    database: str


@dataclass(frozen=True)
class FeatureDataset:
    frame: pd.DataFrame
    symbols: list[str]


def resolve_mysql_settings() -> MysqlSettings:
    return MysqlSettings(
        host=os.getenv("DB_HOST", DEFAULT_DB_HOST).strip() or DEFAULT_DB_HOST,
        port=int(os.getenv("DB_PORT", str(DEFAULT_DB_PORT))),
        user=os.getenv("DB_USER", DEFAULT_DB_USER).strip() or DEFAULT_DB_USER,
        password=os.getenv("DB_PASSWORD", DEFAULT_DB_PASSWORD),
        database=os.getenv("DB_NAME", DEFAULT_DB_NAME).strip() or DEFAULT_DB_NAME,
    )


def open_mysql_connection(settings: MysqlSettings | None = None):
    db = settings or resolve_mysql_settings()
    return mysql.connector.connect(
        host=db.host,
        port=db.port,
        user=db.user,
        password=db.password,
        database=db.database,
        connection_timeout=20,
        autocommit=True,
    )


def load_historical_market_data(
    symbols: list[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    settings: MysqlSettings | None = None,
) -> pd.DataFrame:
    start_value = start_date or DEFAULT_LOOKBACK_START
    params: list[Any] = [start_value]

    query = [
        "SELECT",
        "  UPPER(si.symbol) AS symbol,",
        "  mdb.trade_date AS trade_date,",
        "  COALESCE(mdb.open_price, mdb.close_price) AS open_price,",
        "  COALESCE(mdb.high_price, mdb.close_price) AS high_price,",
        "  COALESCE(mdb.low_price, mdb.close_price) AS low_price,",
        "  mdb.close_price AS close_price,",
        "  COALESCE(mdb.volume, 0) AS volume",
        "FROM market_daily_bars mdb",
        "JOIN stock_instruments si ON si.id = mdb.stock_id",
        "WHERE mdb.trade_date >= %s",
    ]

    if end_date is not None:
        query.append("  AND mdb.trade_date <= %s")
        params.append(end_date)

    if symbols:
        normalized = [symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()]
        if normalized:
            placeholders = ", ".join(["%s"] * len(normalized))
            query.append(f"  AND UPPER(si.symbol) IN ({placeholders})")
            params.extend(normalized)

    query.append("ORDER BY symbol ASC, trade_date ASC")
    sql = "\n".join(query)

    connection = open_mysql_connection(settings=settings)
    try:
        frame = pd.read_sql(sql=sql, con=connection, params=params)
    finally:
        connection.close()

    if frame.empty:
        return frame

    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    numeric_cols = ["open_price", "high_price", "low_price", "close_price", "volume"]
    for col in numeric_cols:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")

    frame = frame.dropna(subset=["symbol", "trade_date", "close_price"])
    frame = frame.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    return frame


def compute_rsi(close_series: pd.Series, period: int = 14) -> pd.Series:
    delta = close_series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def add_technical_indicators(raw_frame: pd.DataFrame) -> pd.DataFrame:
    if raw_frame.empty:
        return raw_frame.copy()

    ordered = raw_frame.sort_values(["symbol", "trade_date"]).copy()

    def _enrich(group: pd.DataFrame) -> pd.DataFrame:
        local = group.copy()
        close = local["close_price"].astype(float)

        local["daily_return"] = close.pct_change()
        local["ema_20"] = close.ewm(span=20, adjust=False).mean()
        local["ema_50"] = close.ewm(span=50, adjust=False).mean()

        ema_12 = close.ewm(span=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, adjust=False).mean()
        local["macd"] = ema_12 - ema_26
        local["macd_signal"] = local["macd"].ewm(span=9, adjust=False).mean()
        local["macd_hist"] = local["macd"] - local["macd_signal"]

        local["rsi_14"] = compute_rsi(close, period=14)

        # Keep per-symbol continuity with forward fill before dropping rows.
        local = local.ffill()
        return local

    with_indicators = ordered.groupby("symbol", group_keys=False).apply(_enrich)
    return with_indicators.reset_index(drop=True)


def build_feature_dataset(
    raw_frame: pd.DataFrame,
    horizon_days: int = 5,
) -> FeatureDataset:
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1")

    enriched = add_technical_indicators(raw_frame)
    if enriched.empty:
        return FeatureDataset(frame=enriched, symbols=[])

    def _build_targets(group: pd.DataFrame) -> pd.DataFrame:
        local = group.copy()
        local["target_close_5d"] = local["close_price"].shift(-horizon_days)
        local["target_return_5d"] = (local["target_close_5d"] / local["close_price"]) - 1.0
        return local

    dataset = enriched.groupby("symbol", group_keys=False).apply(_build_targets).reset_index(drop=True)
    dataset = dataset.groupby("symbol", group_keys=False).apply(lambda group: group.ffill()).reset_index(drop=True)

    required_columns = FEATURE_COLUMNS + ["target_close_5d", "target_return_5d"]
    dataset = dataset.dropna(subset=required_columns)

    symbols = sorted({str(item) for item in dataset["symbol"].unique().tolist()})
    return FeatureDataset(frame=dataset, symbols=symbols)


def build_latest_feature_rows(
    raw_frame: pd.DataFrame,
    as_of_date: date | None = None,
) -> pd.DataFrame:
    if raw_frame.empty:
        return raw_frame.copy()

    enriched = add_technical_indicators(raw_frame)
    if as_of_date is not None:
        cutoff = pd.Timestamp(as_of_date)
        enriched = enriched.loc[enriched["trade_date"] <= cutoff].copy()

    if enriched.empty:
        return enriched

    enriched = enriched.groupby("symbol", group_keys=False).apply(lambda group: group.ffill()).reset_index(drop=True)
    latest = (
        enriched.sort_values(["symbol", "trade_date"])
        .groupby("symbol", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )

    return latest.dropna(subset=FEATURE_COLUMNS + ["close_price"])


def _parse_symbols(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip().upper() for item in raw.split(",") if item and item.strip()]


def _build_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build EGX30 technical features from MySQL historical data")
    parser.add_argument("--output-csv", type=str, default="", help="Optional output CSV path")
    parser.add_argument("--start-date", type=str, default="2016-01-01")
    parser.add_argument("--end-date", type=str, default="")
    parser.add_argument("--symbols", type=str, default="", help="Comma-separated symbols")
    parser.add_argument("--horizon-days", type=int, default=5)
    return parser.parse_args()


def _parse_iso_date(raw: str | None) -> date | None:
    if not raw:
        return None
    value = str(raw).strip()
    if not value:
        return None
    return date.fromisoformat(value)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    args = _build_cli_args()
    raw = load_historical_market_data(
        symbols=_parse_symbols(args.symbols),
        start_date=_parse_iso_date(args.start_date),
        end_date=_parse_iso_date(args.end_date),
    )

    dataset = build_feature_dataset(raw_frame=raw, horizon_days=args.horizon_days)
    LOGGER.info("Feature engineering complete rows=%s symbols=%s", len(dataset.frame), len(dataset.symbols))

    if args.output_csv:
        dataset.frame.to_csv(args.output_csv, index=False)
        LOGGER.info("Saved engineered dataset to %s", args.output_csv)


if __name__ == "__main__":
    main()
