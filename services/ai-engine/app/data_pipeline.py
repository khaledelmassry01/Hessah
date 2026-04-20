from __future__ import annotations

import importlib
import logging
import random
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)
TRADING_DAYS_PER_YEAR = 252
EGX_EXCHANGE = "EGX"
EGX_INTERVAL = "Daily"
DEFAULT_BARS = 252
FETCH_BUFFER_BARS = 900

EGX30_SYMBOLS = [
    "COMI",
    "HRHO",
    "SWDY",
    "ETEL",
    "EFIH",
    "ABUK",
    "FWRY",
    "PHDC",
    "TMGH",
    "ORWE",
    "EAST",
    "AMOC",
    "MFPC",
    "SKPC",
    "CCAP",
    "HELI",
    "PACH",
    "EKHO",
    "MICH",
    "ALCN",
    "ESRS",
    "JUFO",
    "DOMT",
    "GDWA",
    "CIEB",
    "AUTO",
    "BTFH",
    "OBRI",
    "RAYA",
    "CLHO",
]

# Hardcoded metadata fallback when egxpy does not expose sector mapping.
DEFAULT_SECTOR_MAP = {
    "COMI": "BANKS",
    "CIEB": "BANKS",
    "HRHO": "FINANCIAL_SERVICES",
    "BTFH": "FINANCIAL_SERVICES",
    "SWDY": "INDUSTRIALS",
    "AMOC": "ENERGY",
    "MFPC": "ENERGY",
    "SKPC": "ENERGY",
    "ETEL": "TELECOM",
    "EFIH": "CONSUMER_NON_CYCLICAL",
    "ABUK": "HEALTHCARE",
    "FWRY": "TECHNOLOGY",
    "RAYA": "TECHNOLOGY",
    "PHDC": "REAL_ESTATE",
    "TMGH": "REAL_ESTATE",
    "ORWE": "CONSUMER_CYCLICAL",
    "EAST": "CONSUMER_CYCLICAL",
    "CCAP": "FINANCIAL_SERVICES",
    "HELI": "REAL_ESTATE",
    "PACH": "MATERIALS",
    "EKHO": "INDUSTRIALS",
    "MICH": "MATERIALS",
    "ALCN": "MATERIALS",
    "ESRS": "CONSUMER_CYCLICAL",
    "JUFO": "CONSUMER_NON_CYCLICAL",
    "DOMT": "CONSUMER_NON_CYCLICAL",
    "GDWA": "INDUSTRIALS",
    "AUTO": "CONSUMER_CYCLICAL",
    "OBRI": "MATERIALS",
    "CLHO": "HEALTHCARE",
}

DEFAULT_MARKET_CAP_RANK = {
    "COMI": 1,
    "HRHO": 2,
    "SWDY": 3,
    "ETEL": 4,
    "EFIH": 5,
    "ABUK": 6,
    "TMGH": 7,
    "FWRY": 8,
    "PHDC": 9,
    "ORWE": 10,
    "EAST": 11,
    "AMOC": 12,
    "MFPC": 13,
    "SKPC": 14,
    "CCAP": 15,
    "HELI": 16,
    "PACH": 17,
    "EKHO": 18,
    "MICH": 19,
    "ALCN": 20,
    "ESRS": 21,
    "JUFO": 22,
    "DOMT": 23,
    "GDWA": 24,
    "CIEB": 25,
    "AUTO": 26,
    "BTFH": 27,
    "OBRI": 28,
    "RAYA": 29,
    "CLHO": 30,
}


class DataPipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class SymbolSnapshot:
    symbol: str
    sector: str
    current_price: float
    adv30_shares: float
    liquidity_cap_value_egp: float
    volatility_20d: float
    annual_return: float


@dataclass(frozen=True)
class MarketDataset:
    prices: pd.DataFrame
    returns: pd.DataFrame
    snapshots: dict[str, SymbolSnapshot]
    sector_map: dict[str, str]
    suspended_symbols: set[str]
    market_cap_rank: dict[str, int]
    warnings: list[str]


def load_market_dataset(
    as_of_date: date,
    max_adv30_participation: float,
    n_bars: int = DEFAULT_BARS,
) -> MarketDataset:
    if n_bars < 60:
        raise ValueError("n_bars must be >= 60")
    if max_adv30_participation <= 0:
        raise ValueError("max_adv30_participation must be > 0")

    warnings: list[str] = []
    sector_map = dict(DEFAULT_SECTOR_MAP)
    suspended_symbols = _mock_suspended_symbols(as_of_date)

    history_by_symbol: dict[str, pd.DataFrame] = {}
    for symbol in EGX30_SYMBOLS:
        try:
            history_by_symbol[symbol] = _fetch_symbol_ohlcv(
                symbol=symbol,
                as_of_date=as_of_date,
                output_bars=n_bars,
                fetch_bars=max(FETCH_BUFFER_BARS, n_bars),
            )
        except Exception as exc:  # noqa: BLE001 - external source behavior can vary
            warnings.append(f"OHLCV fetch failed for {symbol}: {exc}")

    if len(history_by_symbol) < 8:
        warnings.append("egxpy unavailable or insufficient coverage; synthetic fallback activated")
        history_by_symbol = _generate_mock_ohlcv(EGX30_SYMBOLS, as_of_date, n_bars)
    else:
        missing_symbols = [symbol for symbol in EGX30_SYMBOLS if symbol not in history_by_symbol]
        if missing_symbols:
            history_by_symbol.update(_generate_mock_ohlcv(missing_symbols, as_of_date, n_bars))
            warnings.append(
                "Partial data coverage; synthetic fallback used for: " + ", ".join(missing_symbols)
            )

    prices, volumes = _build_price_volume_frames(history_by_symbol)
    returns = prices.pct_change().replace([np.inf, -np.inf], np.nan).dropna(how="all")

    if returns.shape[0] < 40:
        raise DataPipelineError("Insufficient return history after preprocessing")

    snapshots: dict[str, SymbolSnapshot] = {}
    for symbol in prices.columns:
        close_series = prices[symbol].dropna()
        volume_series = volumes[symbol].dropna()
        if close_series.empty:
            continue

        current_price = float(close_series.iloc[-1])
        adv30_shares = float(volume_series.tail(30).mean()) if not volume_series.empty else 0.0
        if adv30_shares <= 0:
            adv30_shares = 200_000.0

        liquidity_cap_value = adv30_shares * current_price * float(max_adv30_participation)
        volatility_20d = float(returns[symbol].tail(20).std(ddof=0))
        annual_return = float(returns[symbol].mean() * TRADING_DAYS_PER_YEAR)

        snapshots[symbol] = SymbolSnapshot(
            symbol=symbol,
            sector=sector_map.get(symbol, "UNCLASSIFIED"),
            current_price=current_price,
            adv30_shares=adv30_shares,
            liquidity_cap_value_egp=max(0.0, liquidity_cap_value),
            volatility_20d=max(0.0, volatility_20d),
            annual_return=annual_return,
        )

    if len(snapshots) < 2:
        raise DataPipelineError("Failed to build tradable universe")

    return MarketDataset(
        prices=prices,
        returns=returns,
        snapshots=snapshots,
        sector_map=sector_map,
        suspended_symbols=suspended_symbols,
        market_cap_rank=dict(DEFAULT_MARKET_CAP_RANK),
        warnings=warnings,
    )


def build_historical_market_data_payload(
    years: int = 3,
    as_of_date: date | None = None,
) -> tuple[list[dict[str, Any]], str, list[str]]:
    if years < 1:
        raise ValueError("years must be >= 1")

    end_date = as_of_date or date.today()
    output_bars = max(TRADING_DAYS_PER_YEAR * years, DEFAULT_BARS)

    warnings: list[str] = []
    source = "live-provider"
    history_by_symbol: dict[str, pd.DataFrame] = {}

    for symbol in EGX30_SYMBOLS:
        try:
            history_by_symbol[symbol] = _fetch_symbol_ohlcv(
                symbol=symbol,
                as_of_date=end_date,
                output_bars=output_bars,
                fetch_bars=max(FETCH_BUFFER_BARS, output_bars + 64),
            )
        except Exception as exc:  # noqa: BLE001 - external source behavior can vary
            warnings.append(f"OHLCV fetch failed for {symbol}: {exc}")

    if len(history_by_symbol) < 8:
        source = "fallback-synthetic"
        warnings.append("egxpy unavailable or insufficient coverage; synthetic historical payload activated")
        history_by_symbol = _generate_mock_ohlcv(EGX30_SYMBOLS, end_date, output_bars)
    else:
        missing_symbols = [symbol for symbol in EGX30_SYMBOLS if symbol not in history_by_symbol]
        if missing_symbols:
            source = "hybrid-live-synthetic"
            history_by_symbol.update(_generate_mock_ohlcv(missing_symbols, end_date, output_bars))
            warnings.append(
                "Partial historical coverage; synthetic fallback used for: " + ", ".join(missing_symbols)
            )

    payload: list[dict[str, Any]] = []
    for symbol, frame in sorted(history_by_symbol.items(), key=lambda item: item[0]):
        clipped = frame.sort_index().tail(output_bars)

        for index, row in clipped.iterrows():
            trade_date = _coerce_trade_date(index)
            if trade_date is None or trade_date > end_date:
                continue

            close_price = float(row.get("close", 0.0))
            open_price = float(row.get("open", close_price))
            high_price = float(row.get("high", max(open_price, close_price)))
            low_price = float(row.get("low", min(open_price, close_price)))
            volume = int(max(0.0, float(row.get("volume", 0.0))))

            payload.append(
                {
                    "symbol": symbol,
                    "tradeDate": trade_date.isoformat(),
                    "openPrice": round(open_price, 4),
                    "highPrice": round(high_price, 4),
                    "lowPrice": round(low_price, 4),
                    "closePrice": round(close_price, 4),
                    "volume": volume,
                    "halted": False,
                }
            )

    return payload, source, warnings


def _fetch_symbol_ohlcv(
    symbol: str,
    as_of_date: date,
    output_bars: int,
    fetch_bars: int,
) -> pd.DataFrame:
    get_ohlcv_data = _resolve_get_ohlcv_callable()
    if get_ohlcv_data is None:
        raise DataPipelineError("get_OHLCV_data not importable from egxpy")

    # Required integration call shape from API reference.
    raw = get_ohlcv_data(symbol, EGX_EXCHANGE, EGX_INTERVAL, fetch_bars)
    normalized = _normalize_ohlcv_frame(raw)

    if isinstance(normalized.index, pd.DatetimeIndex):
        historical = normalized.loc[normalized.index.date <= as_of_date]
    else:
        historical = normalized

    if historical.empty:
        raise DataPipelineError(f"No historical rows available for {symbol} up to {as_of_date}")

    return historical.tail(output_bars)


def _resolve_get_ohlcv_callable() -> Callable[..., Any] | None:
    module_candidates = ["egxpy", "egxpy.api", "egxpy.client"]

    for module_name in module_candidates:
        try:
            module = importlib.import_module(module_name)
        except Exception:  # noqa: BLE001
            continue

        candidate = getattr(module, "get_OHLCV_data", None)
        if callable(candidate):
            return candidate

    return None


def _normalize_ohlcv_frame(raw: Any) -> pd.DataFrame:
    if isinstance(raw, pd.DataFrame):
        frame = raw.copy()
    elif hasattr(raw, "to_dataframe"):
        frame = raw.to_dataframe()
    elif isinstance(raw, list):
        frame = pd.DataFrame(raw)
    else:
        raise DataPipelineError("Unsupported OHLCV payload format")

    if frame.empty:
        raise DataPipelineError("Empty OHLCV payload")

    cols = {str(col).strip().lower(): col for col in frame.columns}

    date_col = _pick_first_present(cols, ["date", "datetime", "timestamp", "trade_date"])
    open_col = _pick_first_present(cols, ["open", "open_price", "first"])
    high_col = _pick_first_present(cols, ["high", "high_price", "max"])
    low_col = _pick_first_present(cols, ["low", "low_price", "min"])
    close_col = _pick_first_present(cols, ["close", "close_price", "adj_close", "last"])
    volume_col = _pick_first_present(cols, ["volume", "vol", "traded_volume", "turnover_volume"])

    if close_col is None:
        raise DataPipelineError("OHLCV payload missing close column")

    normalized = frame.copy()
    if date_col is not None:
        normalized["_date"] = pd.to_datetime(normalized[date_col], errors="coerce")
        normalized = normalized.dropna(subset=["_date"]).set_index("_date")
    elif normalized.index.name is None:
        normalized.index = pd.date_range(end=pd.Timestamp.today(), periods=len(normalized), freq="B")

    normalized_close = pd.to_numeric(normalized[close_col], errors="coerce")
    if open_col is not None:
        normalized_open = pd.to_numeric(normalized[open_col], errors="coerce")
    else:
        normalized_open = normalized_close

    if high_col is not None:
        normalized_high = pd.to_numeric(normalized[high_col], errors="coerce")
    else:
        normalized_high = normalized_close

    if low_col is not None:
        normalized_low = pd.to_numeric(normalized[low_col], errors="coerce")
    else:
        normalized_low = normalized_close

    if volume_col is not None:
        normalized_volume = pd.to_numeric(normalized[volume_col], errors="coerce")
    else:
        normalized_volume = pd.Series(200_000.0, index=normalized.index)

    clean = pd.DataFrame(
        {
            "open": normalized_open,
            "high": normalized_high,
            "low": normalized_low,
            "close": normalized_close,
            "volume": normalized_volume,
        },
        index=normalized.index,
    )
    clean = clean.dropna(subset=["close"]).sort_index()
    clean["open"] = clean["open"].fillna(clean["close"])
    clean["high"] = clean["high"].fillna(clean["close"])
    clean["low"] = clean["low"].fillna(clean["close"])

    ohlc = clean[["open", "high", "low", "close"]]
    clean["high"] = ohlc.max(axis=1)
    clean["low"] = ohlc.min(axis=1)
    clean["volume"] = clean["volume"].fillna(0.0).clip(lower=0.0)

    if clean.empty:
        raise DataPipelineError("No valid rows in OHLCV payload")

    return clean


def _pick_first_present(column_map: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in column_map:
            return column_map[name]
    return None


def _build_price_volume_frames(history_by_symbol: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    close_series: dict[str, pd.Series] = {}
    volume_series: dict[str, pd.Series] = {}

    for symbol, frame in history_by_symbol.items():
        if frame.empty:
            continue
        close_series[symbol] = frame["close"]
        volume_series[symbol] = frame["volume"]

    prices = pd.DataFrame(close_series).sort_index().ffill().dropna(how="all")
    prices = prices.dropna(axis=1, how="all")

    if prices.empty:
        raise DataPipelineError("Price frame is empty")

    volumes = pd.DataFrame(volume_series).sort_index().reindex(columns=prices.columns).fillna(0.0)
    return prices, volumes


def _mock_suspended_symbols(as_of_date: date) -> set[str]:
    seed = int(as_of_date.strftime("%Y%m%d"))
    rng = random.Random(seed)

    if rng.random() < 0.35:
        count = 1 if rng.random() < 0.75 else 2
        return set(rng.sample(EGX30_SYMBOLS, k=count))
    return set()


def _generate_mock_ohlcv(symbols: list[str], as_of_date: date, n_bars: int) -> dict[str, pd.DataFrame]:
    index = pd.bdate_range(end=pd.Timestamp(as_of_date), periods=n_bars)
    mock: dict[str, pd.DataFrame] = {}

    for symbol in symbols:
        cap_rank = DEFAULT_MARKET_CAP_RANK.get(symbol, 30)
        rank_bias = max(1, min(cap_rank, 30)) / 30.0

        seed = abs(hash((symbol, as_of_date.toordinal()))) % (2**32 - 1)
        rng = np.random.default_rng(seed)

        base_price = 10.0 + (1.0 - rank_bias) * 80.0
        daily_mu = 0.0002 + (1.0 - rank_bias) * 0.0004
        daily_sigma = 0.010 + rank_bias * 0.020

        shocks = rng.normal(loc=daily_mu, scale=daily_sigma, size=n_bars)
        close_prices = base_price * np.exp(np.cumsum(shocks))
        open_prices = np.concatenate(([close_prices[0]], close_prices[:-1]))
        intraday_spread = np.abs(rng.normal(loc=0.006, scale=0.003, size=n_bars))
        high_prices = np.maximum(open_prices, close_prices) * (1.0 + intraday_spread)
        low_prices = np.minimum(open_prices, close_prices) * (1.0 - intraday_spread)
        volumes = rng.integers(low=150_000, high=5_000_000, size=n_bars)

        mock[symbol] = pd.DataFrame(
            {
                "open": open_prices.astype(float),
                "high": high_prices.astype(float),
                "low": low_prices.astype(float),
                "close": close_prices.astype(float),
                "volume": volumes.astype(float),
            },
            index=index,
        )

    LOGGER.warning("Using synthetic OHLCV fallback for symbols: %s", ", ".join(symbols))
    return mock


def _coerce_trade_date(index: Any) -> date | None:
    if isinstance(index, pd.Timestamp):
        if pd.isna(index):
            return None
        return index.date()

    try:
        parsed = pd.to_datetime(index, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.date()
    except Exception:  # noqa: BLE001
        return None
