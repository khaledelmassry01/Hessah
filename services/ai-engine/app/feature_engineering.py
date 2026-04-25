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

from .sentiment_engine import append_market_sentiment_features

LOGGER = logging.getLogger(__name__)

DEFAULT_DB_HOST = "mysql-db"
DEFAULT_DB_PORT = 3306
DEFAULT_DB_NAME = "egx_portfolio"
DEFAULT_DB_USER = "egx_app_user"
DEFAULT_DB_PASSWORD = "EGX_App_7wN!9Qx2#M4Lz8"
DEFAULT_LOOKBACK_START = date(2016, 1, 1)
UREA_SYMBOL_ROOTS = {"ABUK", "MFPC"}
BRENT_SYMBOL_ROOTS = {"AMOC", "SKPC"}

# Unified FEATURE_COLUMNS - 32 features matching feature_factory.py
# Training-Serving Skew Fix: All features must be present in both training and serving
FEATURE_COLUMNS = [
    "daily_return",
    "ema_20",
    "ema_50",
    "ema_200",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "bollinger_mid_20",
    "bollinger_upper_20",
    "bollinger_lower_20",
    "atr_14",
    "usd_egp_return",
    "gold_return",
    "stock_usd_corr_20d",
    "sector_momentum_5d",
    "volume_shock_20d",
    "relative_volume_60d",
    "market_sentiment_score",
    "global_factor_corr_sp500",
    "smart_money_signal",
    "cbe_policy_rate_pct",
    "cbe_rate_changed",
    "alt_news_sentiment_score",
    "alt_urea_price",
    "alt_urea_return_1d",
    "alt_urea_return_5d",
    "alt_urea_zscore_20d",
    "alt_brent_price",
    "alt_brent_return_1d",
    "alt_brent_return_5d",
    "alt_brent_zscore_20d",
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


def load_market_context_data(
    start_date: date,
    end_date: date | None = None,
    settings: MysqlSettings | None = None,
) -> pd.DataFrame:
    params: list[Any] = [start_date]
    query = [
        "SELECT",
        "  trade_date,",
        "  usd_egp_close,",
        "  gold_usd_close,",
        "  cbe_policy_rate_pct,",
        "  cbe_rate_changed",
        "FROM market_context",
        "WHERE trade_date >= %s",
    ]

    if end_date is not None:
        query.append("  AND trade_date <= %s")
        params.append(end_date)

    query.append("ORDER BY trade_date ASC")

    connection = open_mysql_connection(settings=settings)
    try:
        try:
            frame = pd.read_sql(sql="\n".join(query), con=connection, params=params)
             
            # Also fetch alternative data on port 3307
            alt_conn = open_mysql_connection(settings=MysqlSettings(
                host=settings.host if settings else DEFAULT_DB_HOST,
                port=3306,
                user=settings.user if settings else DEFAULT_DB_USER,
                password=settings.password if settings else DEFAULT_DB_PASSWORD,
                database=settings.database if settings else DEFAULT_DB_NAME
            ))
            
            try:
                urea = pd.read_sql("SELECT trade_date, price as alt_urea_price FROM daily_commodities WHERE commodity_name = 'Urea' AND trade_date >= %s", alt_conn, params=[start_date])
                brent = pd.read_sql("SELECT trade_date, price as alt_brent_price FROM daily_commodities WHERE commodity_name = 'Brent Crude' AND trade_date >= %s", alt_conn, params=[start_date])
                news = pd.read_sql("SELECT trade_date, market_sentiment_score as alt_news_sentiment_score FROM daily_market_sentiment WHERE trade_date >= %s", alt_conn, params=[start_date])
                
                urea["trade_date"] = pd.to_datetime(urea["trade_date"], errors="coerce")
                brent["trade_date"] = pd.to_datetime(brent["trade_date"], errors="coerce")
                news["trade_date"] = pd.to_datetime(news["trade_date"], errors="coerce")
                frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")

                frame = frame.merge(urea, on="trade_date", how="left")
                frame = frame.merge(brent, on="trade_date", how="left")
                frame = frame.merge(news, on="trade_date", how="left")
            except Exception as alt_exc:
                LOGGER.warning(f"Failed to fetch alternative data: {alt_exc}")
                frame["alt_urea_price"] = np.nan
                frame["alt_brent_price"] = np.nan
                frame["alt_news_sentiment_score"] = np.nan
            finally:
                alt_conn.close()

        except Exception as e:  # noqa: BLE001
            LOGGER.warning(f"Failed pulling context data: {e}")
            return pd.DataFrame(
                columns=[
                    "trade_date",
                    "usd_egp_return",
                    "gold_return",
                ]
            )
    finally:
        connection.close()

    if frame.empty:
        return pd.DataFrame(
            columns=[
                "trade_date",
                "usd_egp_return",
                "gold_return",
            ]
        )

    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    frame["usd_egp_close"] = pd.to_numeric(frame["usd_egp_close"], errors="coerce")
    frame["gold_usd_close"] = pd.to_numeric(frame["gold_usd_close"], errors="coerce")
    
    if "alt_urea_price" in frame.columns:
        frame["alt_urea_price"] = pd.to_numeric(frame["alt_urea_price"], errors="coerce").ffill()
        frame["alt_brent_price"] = pd.to_numeric(frame["alt_brent_price"], errors="coerce").ffill()
        frame["alt_news_sentiment_score"] = pd.to_numeric(frame["alt_news_sentiment_score"], errors="coerce").ffill()
    else:
        frame["alt_urea_price"] = np.nan
        frame["alt_brent_price"] = np.nan
        frame["alt_news_sentiment_score"] = np.nan

    frame = frame.dropna(subset=["trade_date"]).sort_values("trade_date").drop_duplicates("trade_date", keep="last")
    frame["usd_egp_return"] = frame["usd_egp_close"].pct_change()
    frame["gold_return"] = frame["gold_usd_close"].pct_change()
    frame["cbe_policy_rate_pct"] = pd.to_numeric(frame.get("cbe_policy_rate_pct"), errors="coerce").ffill().bfill()
    frame["cbe_rate_changed"] = pd.to_numeric(frame.get("cbe_rate_changed"), errors="coerce").fillna(0).astype(int)

    return frame[[
        "trade_date", "usd_egp_return", "gold_return",
        "cbe_policy_rate_pct", "cbe_rate_changed",
        "alt_urea_price", "alt_brent_price", "alt_news_sentiment_score"
    ]].reset_index(drop=True)


def _load_sector_mapping(settings: MysqlSettings | None = None) -> dict[str, str]:
    """Load sector mapping from stock_instruments table.

    Training-Serving Skew Fix: Required for sector_momentum_5d calculation.
    """
    sql = """
    SELECT UPPER(symbol) AS symbol, COALESCE(sector_code, 'UNMAPPED') AS sector_code
    FROM stock_instruments
    """
    connection = open_mysql_connection(settings=settings)
    try:
        frame = pd.read_sql(sql=sql, con=connection)
    finally:
        connection.close()

    if frame.empty:
        return {}

    mapping: dict[str, str] = {}
    for _, item in frame.iterrows():
        raw_symbol = str(item.get("symbol") or "").strip().upper()
        if not raw_symbol:
            continue
        # Map both full symbol and root
        mapping[raw_symbol] = str(item.get("sector_code") or "UNMAPPED").strip().upper()
        root = raw_symbol.split(".")[0]
        if root:
            mapping[root] = str(item.get("sector_code") or "UNMAPPED").strip().upper()

    return mapping


def add_contextual_features(raw_frame: pd.DataFrame, settings: MysqlSettings | None = None) -> pd.DataFrame:
    if raw_frame.empty:
        return raw_frame.copy()

    local = raw_frame.sort_values(["symbol", "trade_date"]).copy()
    start_value = pd.Timestamp(local["trade_date"].min()).date()
    end_value = pd.Timestamp(local["trade_date"].max()).date()

    context = load_market_context_data(start_date=start_value, end_date=end_value, settings=settings)
    merged = local.merge(context, on="trade_date", how="left")
    merged[["usd_egp_return", "gold_return", "cbe_policy_rate_pct"]] = merged[
        ["usd_egp_return", "gold_return", "cbe_policy_rate_pct"]
    ].ffill().bfill()
    merged["usd_egp_return"] = merged["usd_egp_return"].fillna(0.0)
    merged["gold_return"] = merged["gold_return"].fillna(0.0)
    merged["cbe_policy_rate_pct"] = merged["cbe_policy_rate_pct"].fillna(0.0)
    merged["cbe_rate_changed"] = merged["cbe_rate_changed"].fillna(0).astype(int)

    # Training-Serving Skew Fix: Add stock_usd_corr_20d (rolling correlation)
    merged["stock_usd_corr_20d"] = (
        merged.groupby("symbol", group_keys=False)
        .apply(
            lambda group: group["daily_return"].rolling(window=20, min_periods=10).corr(group["usd_egp_return"])
        )
        .reset_index(level=0, drop=True)
    )
    merged["stock_usd_corr_20d"] = merged["stock_usd_corr_20d"].fillna(0.0)

    # Training-Serving Skew Fix: Add sector_momentum_5d
    # Load sector mapping from stock_instruments
    sector_map = _load_sector_mapping(settings)
    merged["sector_code"] = merged["symbol"].map(
        lambda s: sector_map.get(str(s).upper().split(".")[0], "UNMAPPED")
    )

    sector_daily = (
        merged.groupby(["trade_date", "sector_code"], as_index=False)["daily_return"]
        .mean()
        .rename(columns={"daily_return": "sector_daily_return"})
        .sort_values(["sector_code", "trade_date"])
    )
    sector_daily["sector_momentum_5d"] = (
        sector_daily.groupby("sector_code")["sector_daily_return"]
        .transform(lambda series: series.rolling(window=5, min_periods=3).mean())
    )
    merged = merged.merge(
        sector_daily[["trade_date", "sector_code", "sector_momentum_5d"]],
        on=["trade_date", "sector_code"],
        how="left",
    )
    merged["sector_momentum_5d"] = merged["sector_momentum_5d"].fillna(0.0)

    # Process alternative data for specific sectors and compute returns/zscores
    symbol_roots = merged["symbol"].astype(str).str.upper().str.split(".").str[0]

    # Training-Serving Skew Fix: Compute urea/brent returns and zscores
    for commodity in ("urea", "brent"):
        price_col = f"alt_{commodity}_price"
        return_1d_col = f"alt_{commodity}_return_1d"
        return_5d_col = f"alt_{commodity}_return_5d"
        zscore_col = f"alt_{commodity}_zscore_20d"
        symbol_roots_set = UREA_SYMBOL_ROOTS if commodity == "urea" else BRENT_SYMBOL_ROOTS

        if price_col in merged.columns:
            # Compute returns
            merged[return_1d_col] = merged[price_col].pct_change(1)
            merged[return_5d_col] = merged[price_col].pct_change(5)

            # Compute zscore
            rolling_mean = merged[price_col].rolling(window=20, min_periods=10).mean()
            rolling_std = merged[price_col].rolling(window=20, min_periods=10).std()
            merged[zscore_col] = (merged[price_col] - rolling_mean) / rolling_std.replace(0.0, np.nan)

            # Zero out for non-relevant symbols
            for col in [price_col, return_1d_col, return_5d_col, zscore_col]:
                merged[col] = np.where(symbol_roots.isin(symbol_roots_set), merged[col], 0.0)
                merged[col] = merged[col].fillna(0.0)

    if "alt_news_sentiment_score" in merged.columns:
        merged["alt_news_sentiment_score"] = merged["alt_news_sentiment_score"].fillna(0.0)

    merged = append_market_sentiment_features(merged)

    return merged.drop(columns=["sector_code"], errors="ignore")


def compute_rsi(close_series: pd.Series, period: int = 14) -> pd.Series:
    delta = close_series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def compute_atr(group: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute Average True Range (ATR) for volatility measurement.

    Ported from feature_factory.py to eliminate training-serving skew.
    """
    high = group["high_price"].astype(float)
    low = group["low_price"].astype(float)
    close = group["close_price"].astype(float)

    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return true_range.rolling(window=period, min_periods=period).mean()


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
        local["ema_200"] = close.ewm(span=200, adjust=False).mean()  # Added for training-serving skew fix

        ema_12 = close.ewm(span=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, adjust=False).mean()
        local["macd"] = ema_12 - ema_26
        local["macd_signal"] = local["macd"].ewm(span=9, adjust=False).mean()
        local["macd_hist"] = local["macd"] - local["macd_signal"]

        # Bollinger Bands - Added for training-serving skew fix
        rolling_std_20 = close.rolling(window=20, min_periods=20).std()
        local["bollinger_mid_20"] = close.rolling(window=20, min_periods=20).mean()
        local["bollinger_upper_20"] = local["bollinger_mid_20"] + (2.0 * rolling_std_20)
        local["bollinger_lower_20"] = local["bollinger_mid_20"] - (2.0 * rolling_std_20)

        local["rsi_14"] = compute_rsi(close, period=14)
        local["atr_14"] = compute_atr(local, period=14)  # Added for training-serving skew fix

        volume_float = local["volume"].astype(float)
        local["volume_60d_avg"] = volume_float.rolling(window=60, min_periods=20).mean()
        local["volume_20d_avg"] = volume_float.rolling(window=20, min_periods=5).mean()
        safe_volume_avg_60 = local["volume_60d_avg"].replace(0.0, np.nan)
        safe_volume_avg_20 = local["volume_20d_avg"].replace(0.0, np.nan)
        local["relative_volume_60d"] = (volume_float / safe_volume_avg_60).replace([np.inf, -np.inf], np.nan)
        local["relative_volume_60d"] = local["relative_volume_60d"].fillna(1.0)
        local["volume_shock_20d"] = (volume_float / safe_volume_avg_20).replace([np.inf, -np.inf], np.nan)
        local["volume_shock_20d"] = local["volume_shock_20d"].fillna(1.0)

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
    enriched = add_contextual_features(enriched)
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
    enriched = add_contextual_features(enriched)
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
