from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)

DEFAULT_SENTIMENT_CACHE = Path(__file__).resolve().parent / "data" / "sp500_cache.csv"
STOOQ_API_KEY = "hJT6KeBilo3mhwfEVpx5u8QcgWLj2t9X"
SP500_STOOQ_BASE_URL = "https://stooq.com/q/d/l/?s=^spx&i=d&apikey={apikey}&f={start}&t={end}"


def _safe_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.zeros(len(frame), dtype=float), index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def _read_sp500_cache(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["trade_date", "sp500_return"])

    try:
        cache = pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Failed reading S&P500 cache %s: %s", path, exc)
        return pd.DataFrame(columns=["trade_date", "sp500_return"])

    if cache.empty:
        return pd.DataFrame(columns=["trade_date", "sp500_return"])

    cache["trade_date"] = pd.to_datetime(cache.get("trade_date"), errors="coerce")
    cache["sp500_return"] = pd.to_numeric(cache.get("sp500_return"), errors="coerce")
    cache = cache.dropna(subset=["trade_date", "sp500_return"]).drop_duplicates(subset=["trade_date"], keep="last")
    return cache.sort_values("trade_date").reset_index(drop=True)


def _download_sp500_prices(start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    url = SP500_STOOQ_BASE_URL.format(
        apikey=STOOQ_API_KEY,
        start=start_str,
        end=end_str
    )

    try:
        LOGGER.info("Fetching S&P500 data from Stooq: %s", url.replace(STOOQ_API_KEY, "REDACTED"))
        # Use a bounded network call so model training does not hang when upstream is unavailable.
        with urlopen(url, timeout=15) as response:
            payload = response.read()
        frame = pd.read_csv(io.BytesIO(payload))
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("S&P500 download failed from Stooq: %s", exc)
        return pd.DataFrame(columns=["trade_date", "close_price"])

    if frame.empty or "Date" not in frame.columns or "Close" not in frame.columns:
        LOGGER.warning("Stooq returned empty or invalid S&P500 data")
        return pd.DataFrame(columns=["trade_date", "close_price"])

    frame = frame.rename(columns={"Date": "trade_date", "Close": "close_price"})
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    frame["close_price"] = pd.to_numeric(frame["close_price"], errors="coerce")
    frame = frame.dropna(subset=["trade_date", "close_price"]).sort_values("trade_date")
    
    if not frame.empty:
        return frame[["trade_date", "close_price"]].reset_index(drop=True)

    return pd.DataFrame(columns=["trade_date", "close_price"])


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


def _load_sp500_returns(start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    cache_path = Path(os.getenv("SP500_CACHE_CSV", str(DEFAULT_SENTIMENT_CACHE))).expanduser()
    cache = _read_sp500_cache(cache_path)

    if not cache.empty:
        min_date = pd.Timestamp(cache["trade_date"].min())
        max_date = pd.Timestamp(cache["trade_date"].max())
        if min_date <= start_date and max_date >= end_date:
            return cache

    downloaded_prices = _download_sp500_prices(start_date, end_date)
    if downloaded_prices.empty:
        return cache

    downloaded_prices["sp500_return"] = downloaded_prices["close_price"].pct_change()
    downloaded = downloaded_prices.dropna(subset=["sp500_return"])[["trade_date", "sp500_return"]]

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        downloaded.to_csv(cache_path, index=False)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Failed writing S&P500 cache %s: %s", cache_path, exc)

    if cache.empty:
        return downloaded.reset_index(drop=True)

    combined = pd.concat([cache, downloaded], ignore_index=True)
    combined = combined.dropna(subset=["trade_date", "sp500_return"])
    combined = combined.drop_duplicates(subset=["trade_date"], keep="last")
    return combined.sort_values("trade_date").reset_index(drop=True)


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
    sp500 = _load_sp500_returns(start_date=start_date, end_date=end_date)

    if sp500.empty:
        LOGGER.info("S&P500 data unavailable, using EGX30 volatility proxy for S&P500 correlation")
        # Use EGX30 volatility-based proxy for S&P500 correlation
        egx30_returns = pd.to_numeric(daily.get("egx30_return"), errors="coerce").fillna(0.0)
        daily["sp500_return"] = _compute_egx30_volatility_proxy(egx30_returns).to_numpy(dtype=float)
    else:
        daily = daily.merge(sp500, on="trade_date", how="left")
        daily["sp500_return"] = pd.to_numeric(daily.get("sp500_return"), errors="coerce")
        daily["sp500_return"] = daily["sp500_return"].ffill().bfill().fillna(0.0)

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
