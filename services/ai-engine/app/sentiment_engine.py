from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)


def _safe_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.zeros(len(frame), dtype=float), index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)



def _compute_egx30_volatility_proxy(daily_returns: pd.Series, window: int = 20) -> pd.Series:
    """
    Compute S&P500 proxy using EGX30 volatility.
    Logic: High EGX30 volatility correlates with global market stress (S&P500 downside).
    Returns a synthetic 'sp500_return' series based on EGX30 volatility patterns.
    """
    returns_clean = pd.to_numeric(daily_returns, errors="coerce").fillna(0.0)

    # Compute rolling volatility (annualized)
    rolling_vol = returns_clean.rolling(window=window, min_periods=5).std() * np.sqrt(252)
    rolling_vol = rolling_vol.fillna(rolling_vol.median())

    # Normalize volatility to create correlation-like signal
    vol_normalized = (rolling_vol - rolling_vol.min()) / (rolling_vol.max() - rolling_vol.min() + 1e-10)

    # EGX30 returns component (smoothed)
    egx_smooth = returns_clean.rolling(window=3, min_periods=1).mean()

    # Proxy formula: EGX30 returns dampened by volatility factor
    # High volatility = more negative correlation (market stress)
    # Low volatility = positive correlation (normal markets)
    vol_factor = 1.0 - (2.0 * vol_normalized)  # Range: -1 (high vol) to +1 (low vol)

    proxy = egx_smooth * 0.6 + vol_factor * 0.004  # Scale to realistic daily returns
    return proxy.fillna(0.0)


def _load_daily_market_sentiment(start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    """Load precomputed daily market sentiment from the database (no external calls)."""
    # Local import to avoid circular dependency with feature_engineering
    from .feature_engineering import _read_sql_frame, resolve_mysql_settings, load_market_context_data

    resolved_settings = resolve_mysql_settings()
    params = [start_date]
    query = [
        "SELECT trade_date, market_sentiment_score",
        "FROM daily_market_sentiment",
        "WHERE trade_date >= %s",
    ]
    if end_date is not None:
        query.append("AND trade_date <= %s")
        params.append(end_date)

    query.append("ORDER BY trade_date ASC")

    try:
        frame = _read_sql_frame(sql="\n".join(query), params=params, settings=resolved_settings)
        if frame.empty:
            return frame

        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
        frame["market_sentiment_score"] = pd.to_numeric(frame.get("market_sentiment_score"), errors="coerce")
        frame = frame.dropna(subset=["trade_date"]).drop_duplicates(subset=["trade_date"], keep="last")
        return frame.sort_values("trade_date").reset_index(drop=True)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Failed loading daily_market_sentiment from DB: %s", exc)
        return pd.DataFrame(columns=["trade_date", "market_sentiment_score"])


def build_market_sentiment_frame(input_frame: pd.DataFrame) -> pd.DataFrame:
    if input_frame.empty:
        return pd.DataFrame(columns=["trade_date", "market_sentiment_score", "global_factor_corr_sp500", "smart_money_signal"])

    local = input_frame.copy()
    local["trade_date"] = pd.to_datetime(local.get("trade_date"), errors="coerce")
    local = local.dropna(subset=["trade_date"])
    if local.empty:
        return pd.DataFrame(columns=["trade_date", "market_sentiment_score", "global_factor_corr_sp500", "smart_money_signal"])

    daily = (
        local.groupby("trade_date", as_index=False)
        .agg(
            {
                "daily_return": "mean",
                "volume_shock_20d": "median",
                "usd_egp_return": "mean" if "usd_egp_return" in local.columns else "first",
                "gold_return": "mean" if "gold_return" in local.columns else "first",
            }
        )
        .sort_values("trade_date")
    )

    daily = daily.rename(
        columns={
            "daily_return": "egx30_return",
            "volume_shock_20d": "volume_shock",
        }
    )
    daily["egx30_return"] = pd.to_numeric(daily["egx30_return"], errors="coerce").fillna(0.0)
    daily["volume_shock"] = pd.to_numeric(daily["volume_shock"], errors="coerce").fillna(0.0)

    start_date = pd.Timestamp(daily["trade_date"].min())
    end_date = pd.Timestamp(daily["trade_date"].max())

    # Prefer precomputed daily_market_sentiment table (DB-backed). This removes any external network calls.
    db_sentiment = _load_daily_market_sentiment(start_date=start_date, end_date=end_date)

    if not db_sentiment.empty and "market_sentiment_score" in db_sentiment.columns:
        # Use DB-provided market sentiment as a global factor proxy instead of external S&P500 fetch
        merged = daily.merge(db_sentiment.rename(columns={"market_sentiment_score": "sp500_proxy"}), on="trade_date", how="left")
        merged["sp500_proxy"] = pd.to_numeric(merged.get("sp500_proxy"), errors="coerce").ffill().bfill().fillna(0.0)
        global_factor = (
            merged["egx30_return"]
            .rolling(window=20, min_periods=8)
            .corr(merged["sp500_proxy"])
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0.0)
            .clip(lower=-1.0, upper=1.0)
        )
        daily = merged
    else:
        LOGGER.info("DB market sentiment unavailable, using EGX30 volatility proxy for global factor")
        egx30_returns = pd.to_numeric(daily.get("egx30_return"), errors="coerce").fillna(0.0)
        daily["sp500_return"] = _compute_egx30_volatility_proxy(egx30_returns).to_numpy(dtype=float)

        global_factor = (
            daily["egx30_return"]
            .rolling(window=20, min_periods=8)
            .corr(daily["sp500_return"])
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0.0)
            .clip(lower=-1.0, upper=1.0)
        )

    volume_component = np.tanh(daily["volume_shock"].to_numpy(dtype=float))
    direction_component = np.sign(daily["egx30_return"].to_numpy(dtype=float))
    smart_money_signal = np.clip(
        (0.65 * volume_component * direction_component) + (0.35 * volume_component),
        -1.0,
        1.0,
    )

    sentiment_score = np.clip(
        (0.65 * global_factor.to_numpy(dtype=float)) + (0.35 * smart_money_signal),
        -1.0,
        1.0,
    )

    return pd.DataFrame(
        {
            "trade_date": daily["trade_date"],
            "market_sentiment_score": sentiment_score,
            "global_factor_corr_sp500": global_factor.to_numpy(dtype=float),
            "smart_money_signal": smart_money_signal,
        }
    )


def append_market_sentiment_features(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    sentiment_frame = build_market_sentiment_frame(frame)
    if sentiment_frame.empty:
        local = frame.copy()
        local["market_sentiment_score"] = 0.0
        local["global_factor_corr_sp500"] = 0.0
        local["smart_money_signal"] = 0.0
        return local

    local = frame.copy()
    local["trade_date"] = pd.to_datetime(local.get("trade_date"), errors="coerce")
    merged = local.merge(sentiment_frame, on="trade_date", how="left")
    fill_cols = ["market_sentiment_score", "global_factor_corr_sp500", "smart_money_signal"]
    merged[fill_cols] = merged[fill_cols].ffill().bfill().fillna(0.0)
    return merged
