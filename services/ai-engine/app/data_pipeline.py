from __future__ import annotations

import logging
import os
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)
TRADING_DAYS_PER_YEAR = 252
DEFAULT_BARS = 252
EGX_SUFFIX = ".CA"
SYMBOL_MAX_LENGTH = 16
MINIMUM_RETURNS_OBSERVATIONS = 40
HISTORICAL_DATA_DIR_ENV_VAR = "HISTORICAL_DATA_DIR"
DEFAULT_HISTORICAL_DATA_DIR = Path("/app/data/historical")
LOCAL_HISTORICAL_DATA_DIR = Path(__file__).resolve().parent / "data" / "historical"

# Hardcoded canonical symbol map to guarantee CSV and API symbol compatibility.
EGX30_SYMBOL_TO_CANONICAL = {
    "COMI": "COMI.CA",
    "HRHO": "HRHO.CA",
    "SWDY": "SWDY.CA",
    "ETEL": "ETEL.CA",
    "EFIH": "EFIH.CA",
    "ABUK": "ABUK.CA",
    "FWRY": "FWRY.CA",
    "PHDC": "PHDC.CA",
    "TMGH": "TMGH.CA",
    "ORWE": "ORWE.CA",
    "EAST": "EAST.CA",
    "AMOC": "AMOC.CA",
    "MFPC": "MFPC.CA",
    "SKPC": "SKPC.CA",
    "CCAP": "CCAP.CA",
    "HELI": "HELI.CA",
    "ORAS": "ORAS.CA",
    "EKHO": "EKHO.CA",
    "MICH": "MICH.CA",
    "ALCN": "ALCN.CA",
    "ORHD": "ORHD.CA",
    "JUFO": "JUFO.CA",
    "DOMT": "DOMT.CA",
    "GDWA": "GDWA.CA",
    "CIEB": "CIEB.CA",
    "AUTO": "AUTO.CA",
    "BTFH": "BTFH.CA",
    "OBRI": "OBRI.CA",
    "RAYA": "RAYA.CA",
    "CLHO": "CLHO.CA",
}

EGX30_SYMBOLS = list(EGX30_SYMBOL_TO_CANONICAL.keys())
EGX30_CANONICAL_SYMBOLS = list(EGX30_SYMBOL_TO_CANONICAL.values())

SYMBOL_ALIAS_TO_CANONICAL: dict[str, str] = {}
for _base_symbol, _canonical_symbol in EGX30_SYMBOL_TO_CANONICAL.items():
    SYMBOL_ALIAS_TO_CANONICAL[_base_symbol] = _canonical_symbol
    SYMBOL_ALIAS_TO_CANONICAL[_canonical_symbol] = _canonical_symbol
    SYMBOL_ALIAS_TO_CANONICAL[f"{_base_symbol}.CAI"] = _canonical_symbol
    SYMBOL_ALIAS_TO_CANONICAL[f"{_base_symbol}.EGX"] = _canonical_symbol

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
    "ORAS": "INDUSTRIALS",
    "EKHO": "INDUSTRIALS",
    "MICH": "MATERIALS",
    "ALCN": "MATERIALS",
    "ORHD": "REAL_ESTATE",
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
    "ORAS": 17,
    "EKHO": 18,
    "MICH": 19,
    "ALCN": 20,
    "ORHD": 21,
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


def resolve_historical_data_dir() -> Path:
    configured = os.getenv(HISTORICAL_DATA_DIR_ENV_VAR, str(DEFAULT_HISTORICAL_DATA_DIR)).strip()
    if configured:
        configured_path = Path(configured)
        if configured_path.exists():
            return configured_path

    return LOCAL_HISTORICAL_DATA_DIR


def canonicalize_symbol(raw_symbol: str | None, allow_unmapped: bool = False) -> str | None:
    if raw_symbol is None:
        return None

    symbol = str(raw_symbol).strip().upper()
    if not symbol:
        return None

    if ":" in symbol:
        symbol = symbol.split(":")[-1]

    if symbol in SYMBOL_ALIAS_TO_CANONICAL:
        return SYMBOL_ALIAS_TO_CANONICAL[symbol]

    base = to_base_symbol(symbol)
    if base is None:
        return None

    mapped = EGX30_SYMBOL_TO_CANONICAL.get(base)
    if mapped is not None:
        return mapped

    if not allow_unmapped:
        return None

    candidate = f"{base}{EGX_SUFFIX}"
    return candidate[:SYMBOL_MAX_LENGTH]


def to_base_symbol(raw_symbol: str | None) -> str | None:
    if raw_symbol is None:
        return None

    symbol = str(raw_symbol).strip().upper()
    if not symbol:
        return None

    if ":" in symbol:
        symbol = symbol.split(":")[-1]

    if symbol.endswith(EGX_SUFFIX):
        symbol = symbol[: -len(EGX_SUFFIX)]
    elif "." in symbol:
        symbol = symbol.split(".")[0]

    symbol = "".join(ch for ch in symbol if ch.isalnum() or ch in {"_", "-"})
    if not symbol:
        return None

    return symbol[:SYMBOL_MAX_LENGTH]


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

    # Try TradingView first, fall back to local CSV
    history_by_symbol: dict[str, pd.DataFrame] = {}
    source = "tradingview"
    try:
        history_by_symbol = _load_history_from_tradingview(
            as_of_date=as_of_date,
            n_bars=n_bars,
            warnings=warnings,
        )
        LOGGER.info("Using TradingView as primary data source")
    except DataPipelineError as exc:
        warnings.append(f"TradingView load failed ({exc}), falling back to local CSV")
        LOGGER.warning(warnings[-1])
        history_by_symbol = _load_history_from_csv(
            as_of_date=as_of_date,
            n_bars=n_bars,
            warnings=warnings,
        )
        source = "local-csv"

    prices, volumes = _build_price_volume_frames(history_by_symbol)
    returns = prices.pct_change().replace([np.inf, -np.inf], np.nan).dropna(how="all")

    if returns.shape[0] < MINIMUM_RETURNS_OBSERVATIONS:
        raise DataPipelineError("Insufficient return history after preprocessing")

    sector_map = {
        symbol: _resolve_sector(symbol)
        for symbol in prices.columns
    }
    market_cap_rank = {
        symbol: DEFAULT_MARKET_CAP_RANK.get(to_base_symbol(symbol) or symbol, 30)
        for symbol in prices.columns
    }
    suspended_symbols = _mock_suspended_symbols(as_of_date, list(prices.columns))

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
        market_cap_rank=market_cap_rank,
        warnings=warnings,
    )


def build_historical_market_data_payload(
    years: int = 3,
    as_of_date: date | None = None,
) -> tuple[list[dict[str, Any]], str, list[str]]:
    if years < 1:
        raise ValueError("years must be >= 1")

    end_date = as_of_date or date.today()
    output_bars = max(TRADING_DAYS_PER_YEAR * years, TRADING_DAYS_PER_YEAR)
    start_date = end_date - timedelta(days=366 * years)
    warnings: list[str] = []
    source = "tradingview"

    # Try TradingView first, fall back to local CSV
    history_by_symbol: dict[str, pd.DataFrame] = {}
    try:
        history_by_symbol = _load_history_from_tradingview(
            as_of_date=end_date,
            n_bars=output_bars,
            warnings=warnings,
        )
    except DataPipelineError as exc:
        warnings.append(f"TradingView load failed ({exc}), falling back to local CSV")
        LOGGER.warning(warnings[-1])
        history_by_symbol = _load_history_from_csv(
            as_of_date=end_date,
            n_bars=output_bars,
            warnings=warnings,
        )
        source = "local-csv"

    payload: list[dict[str, Any]] = []
    for symbol, frame in sorted(history_by_symbol.items(), key=lambda item: item[0]):
        clipped = frame.sort_index().tail(output_bars)

        for index, row in clipped.iterrows():
            trade_date = _coerce_trade_date(index)
            if trade_date is None or trade_date > end_date:
                continue
            if trade_date < start_date:
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


def _load_history_from_csv(
    as_of_date: date,
    n_bars: int,
    warnings: list[str],
) -> dict[str, pd.DataFrame]:
    historical_dir = resolve_historical_data_dir()
    if not historical_dir.exists():
        raise DataPipelineError(
            f"Historical CSV directory does not exist: {historical_dir}. Run data_seeder.py first."
        )

    csv_files = sorted(historical_dir.glob("*.csv"))
    if not csv_files:
        raise DataPipelineError(
            f"No CSV files found under {historical_dir}. Run data_seeder.py first."
        )

    history_by_symbol: dict[str, pd.DataFrame] = {}
    window_size = max(60, int(n_bars))

    for csv_file in csv_files:
        symbol, frame, warning = _read_history_csv(csv_file)
        if warning:
            warnings.append(warning)
        if symbol is None or frame is None or frame.empty:
            continue

        frame = frame.loc[frame.index.date <= as_of_date]
        if frame.empty:
            continue

        clipped = frame.sort_index().tail(window_size)
        if clipped.empty:
            continue

        history_by_symbol[symbol] = clipped

    missing_expected = [
        symbol
        for symbol in EGX30_CANONICAL_SYMBOLS
        if symbol not in history_by_symbol
    ]
    if missing_expected:
        warnings.append(
            "Missing historical CSVs for symbols: " + ", ".join(missing_expected)
        )

    if not history_by_symbol:
        raise DataPipelineError(
            f"No usable historical CSV rows found under {historical_dir}."
        )

    LOGGER.info(
        "Loaded local CSV history: symbols=%s directory=%s",
        len(history_by_symbol),
        historical_dir,
    )

    return history_by_symbol


def _read_history_csv(csv_file: Path) -> tuple[str | None, pd.DataFrame | None, str | None]:
    try:
        raw = pd.read_csv(csv_file)
    except Exception as exc:  # noqa: BLE001
        return None, None, f"Failed to read {csv_file.name}: {exc}"

    if raw.empty:
        return None, None, f"Historical CSV {csv_file.name} is empty"

    symbol = _resolve_symbol_from_frame(raw, csv_file)
    if symbol is None:
        return None, None, f"Could not resolve canonical symbol for {csv_file.name}"

    column_map = {str(column).strip().lower(): column for column in raw.columns}
    date_col = _pick_first_present(column_map, ["trade_date", "date", "datetime", "timestamp"])
    open_col = _pick_first_present(column_map, ["open", "open_price", "o"])
    high_col = _pick_first_present(column_map, ["high", "high_price", "h"])
    low_col = _pick_first_present(column_map, ["low", "low_price", "l"])
    close_col = _pick_first_present(column_map, ["close", "close_price", "adj_close", "c"])
    volume_col = _pick_first_present(column_map, ["volume", "vol", "v"])

    if date_col is None or close_col is None:
        return None, None, f"Historical CSV {csv_file.name} must include date and close columns"

    normalized = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(raw[date_col], errors="coerce"),
            "close": pd.to_numeric(raw[close_col], errors="coerce"),
            "open": pd.to_numeric(raw[open_col], errors="coerce") if open_col is not None else np.nan,
            "high": pd.to_numeric(raw[high_col], errors="coerce") if high_col is not None else np.nan,
            "low": pd.to_numeric(raw[low_col], errors="coerce") if low_col is not None else np.nan,
            "volume": pd.to_numeric(raw[volume_col], errors="coerce") if volume_col is not None else np.nan,
        }
    )

    normalized = normalized.dropna(subset=["trade_date", "close"])
    if normalized.empty:
        return None, None, f"Historical CSV {csv_file.name} has no valid trade_date/close rows"

    normalized["open"] = normalized["open"].fillna(normalized["close"])
    normalized["high"] = normalized["high"].fillna(normalized["close"])
    normalized["low"] = normalized["low"].fillna(normalized["close"])
    normalized["volume"] = normalized["volume"].fillna(0.0).clip(lower=0.0)

    ohlc = normalized[["open", "high", "low", "close"]]
    normalized["high"] = ohlc.max(axis=1)
    normalized["low"] = ohlc.min(axis=1)

    normalized = normalized.set_index("trade_date").sort_index()
    normalized = normalized[~normalized.index.duplicated(keep="last")]

    return symbol, normalized[["open", "high", "low", "close", "volume"]], None


def _resolve_symbol_from_frame(raw: pd.DataFrame, csv_file: Path) -> str | None:
    column_map = {str(column).strip().lower(): column for column in raw.columns}
    symbol_col = _pick_first_present(column_map, ["symbol", "ticker", "code"])

    if symbol_col is not None:
        for raw_value in raw[symbol_col].dropna().tolist():
            canonical = canonicalize_symbol(str(raw_value), allow_unmapped=False)
            if canonical is not None:
                return canonical

    return canonicalize_symbol(csv_file.stem, allow_unmapped=False)


def _resolve_sector(symbol: str) -> str:
    base_symbol = to_base_symbol(symbol)
    if base_symbol is None:
        return "UNCLASSIFIED"

    return DEFAULT_SECTOR_MAP.get(base_symbol, "UNCLASSIFIED")


def _load_history_from_tradingview(
    as_of_date: date,
    n_bars: int,
    warnings: list[str],
) -> dict[str, pd.DataFrame]:
    """
    Load historical OHLCV data from TradingView for all EGX30 symbols.

    Falls back gracefully per-symbol: if TradingView fails for one symbol,
    that symbol is skipped rather than aborting the entire load.

    Returns a dict mapping canonical symbol -> DataFrame with DatetimeIndex
    and columns [open, high, low, close, volume].
    """
    from .data_fetcher import DataFetcher

    fetcher = DataFetcher()
    history_by_symbol: dict[str, pd.DataFrame] = {}
    window_size = max(60, int(n_bars))

    for canonical in EGX30_CANONICAL_SYMBOLS:
        try:
            df = fetcher.fetch_symbol_data_tradingview(
                symbol=canonical,
                start_date=as_of_date - timedelta(days=366 * 15),
                end_date=as_of_date,
                n_bars=window_size,
            )
            if df is None or df.empty:
                warnings.append(f"TradingView returned no data for {canonical}")
                continue

            # Filter to as_of_date and clip to window
            df = df.loc[df.index.date <= as_of_date]
            if df.empty:
                continue
            clipped = df.sort_index().tail(window_size)
            if clipped.empty:
                continue

            history_by_symbol[canonical] = clipped
            LOGGER.info(f"TradingView loaded {len(clipped)} bars for {canonical}")

        except Exception as exc:  # noqa: BLE001
            warnings.append(f"TradingView fetch failed for {canonical}: {exc}")
            continue

    missing_expected = [
        symbol
        for symbol in EGX30_CANONICAL_SYMBOLS
        if symbol not in history_by_symbol
    ]
    if missing_expected:
        warnings.append(
            "TradingView missing data for symbols: " + ", ".join(missing_expected)
        )

    if not history_by_symbol:
        raise DataPipelineError(
            "TradingView returned no data for any EGX30 symbol"
        )

    LOGGER.info(
        "Loaded TradingView history: symbols=%s",
        len(history_by_symbol),
    )

    return history_by_symbol


def _normalize_ohlcv_frame(raw: Any) -> pd.DataFrame:
    del raw
    raise DataPipelineError("Live OHLCV normalization has been removed; local CSVs are required")


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


def _mock_suspended_symbols(as_of_date: date, candidates: list[str] | None = None) -> set[str]:
    if candidates is None:
        candidates = list(EGX30_CANONICAL_SYMBOLS)

    if not candidates:
        return set()

    seed = int(as_of_date.strftime("%Y%m%d"))
    rng = random.Random(seed)

    if rng.random() < 0.35:
        max_count = min(2, len(candidates))
        count = 1 if max_count == 1 else (1 if rng.random() < 0.75 else max_count)
        return set(rng.sample(candidates, k=count))

    return set()


def _generate_mock_ohlcv(symbols: list[str], as_of_date: date, n_bars: int) -> dict[str, pd.DataFrame]:
    del symbols, as_of_date, n_bars
    raise DataPipelineError("Synthetic OHLCV generation has been disabled; local CSVs are required")


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
