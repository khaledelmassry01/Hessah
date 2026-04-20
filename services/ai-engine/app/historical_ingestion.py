from __future__ import annotations

import csv
import json
import logging
import os
import random
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib import error as url_error
from urllib import request as url_request

import pandas as pd
import requests
import yfinance as yf

from .data_pipeline import EGX30_SYMBOLS

DEFAULT_CORE_BACKEND_URL = "http://core-backend:8081"
DEFAULT_MARKET_DATA_BULK_PATH = "/api/core/market-data/bulk"
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_YEARS = 5
YAHOO_SUFFIX = ".CA"
YAHOO_MIN_DELAY_SECONDS = 2.0
YAHOO_MAX_DELAY_SECONDS = 5.0
YAHOO_RATE_LIMIT_BACKOFF_SECONDS = 5.0
YAHOO_MAX_RETRIES = 3
YAHOO_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_CACHE_FILE = os.path.join(tempfile.gettempdir(), "egx_yahoo_history_cache.json")
DEFAULT_SEED_CSV_FILE = Path(__file__).resolve().parent / "data" / "egx30_snapshot.csv"
EXPECTED_MIN_REAL_ROWS = 40000

LOGGER = logging.getLogger(__name__)


def ingest_historical_market_data_to_core(years: int = DEFAULT_YEARS) -> dict[str, Any]:
    payload, stats, warnings = fetch_historical_data(years=years)
    source = str(stats.get("source") or "yahoo-finance-real")

    if not payload:
        return {
            "status": "FAILED",
            "source": source,
            "provider": "yfinance",
            "years": years,
            "symbolsRequested": stats.get("symbolsRequested", 0),
            "symbolsWithData": stats.get("symbolsWithData", 0),
            "rowsPrepared": 0,
            "rowsSynced": 0,
            "warnings": warnings + ["No REAL Yahoo Finance rows were prepared for ingestion"],
        }

    if len(payload) < EXPECTED_MIN_REAL_ROWS:
        warnings.append(
            "Prepared row count is lower than expected for 5-year ingestion. "
            f"Prepared={len(payload)}, expected approximately 40k-60k for 30-50 symbols."
        )

    LOGGER.info(
        "Yahoo Finance REAL historical fetch succeeded: symbolsRequested=%s symbolsWithData=%s rowsPrepared=%s years=%s",
        stats.get("symbolsRequested", 0),
        stats.get("symbolsWithData", 0),
        len(payload),
        years,
    )

    core_base_url = os.getenv("CORE_BACKEND_URL", DEFAULT_CORE_BACKEND_URL).rstrip("/")
    bulk_url = f"{core_base_url}{DEFAULT_MARKET_DATA_BULK_PATH}"

    totals = {
        "received": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "unknownSymbols": 0,
    }

    for chunk in _chunked(payload, DEFAULT_CHUNK_SIZE):
        status_code, response_payload = _post_json(bulk_url, chunk)
        if status_code < 200 or status_code >= 300:
            raise RuntimeError(f"Market data bulk sync failed with HTTP {status_code}: {response_payload}")

        if isinstance(response_payload, dict):
            totals["received"] += int(response_payload.get("received") or 0)
            totals["inserted"] += int(response_payload.get("inserted") or 0)
            totals["updated"] += int(response_payload.get("updated") or 0)
            totals["skipped"] += int(response_payload.get("skipped") or 0)
            totals["unknownSymbols"] += int(response_payload.get("unknownSymbols") or 0)

    return {
        "status": "SUCCESS",
        "source": source,
        "provider": "yfinance",
        "years": years,
        "symbolsRequested": stats.get("symbolsRequested", 0),
        "symbolsWithData": stats.get("symbolsWithData", 0),
        "symbolsWithoutData": stats.get("symbolsWithoutData", 0),
        "rowsPrepared": len(payload),
        "rowsSynced": totals["received"],
        "inserted": totals["inserted"],
        "updated": totals["updated"],
        "skipped": totals["skipped"],
        "unknownSymbols": totals["unknownSymbols"],
        "coreBulkUrl": bulk_url,
        "warnings": warnings,
    }


def fetch_historical_data(years: int = DEFAULT_YEARS) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    if years < 1:
        raise ValueError("years must be >= 1")

    warnings: list[str] = []
    symbols = _resolve_symbols()
    symbol_ticker_pairs = [(symbol, _to_yahoo_ticker(symbol)) for symbol in symbols]
    yahoo_session = _build_yahoo_session()

    end_date = date.today() + timedelta(days=1)
    start_date = end_date - timedelta(days=366 * years)

    LOGGER.info(
        "Starting REAL Yahoo Finance historical fetch: tickers=%s start=%s end=%s",
        len(symbol_ticker_pairs),
        start_date.isoformat(),
        end_date.isoformat(),
    )

    cache_file = _cache_file_path()
    cache_payload = _load_symbol_cache(cache_file)
    cache_symbols = cache_payload.setdefault("symbols", {})
    seed_rows_by_symbol = _load_seed_rows(DEFAULT_SEED_CSV_FILE, warnings)

    payload: list[dict[str, Any]] = []
    symbols_with_data = 0
    symbols_without_data = 0
    used_seed_fallback = False

    for symbol, ticker in symbol_ticker_pairs:
        LOGGER.info("Fetching Yahoo Finance history for symbol=%s ticker=%s", symbol, ticker)

        cached_rows = _read_cached_symbol_rows(cache_symbols, symbol)
        if cached_rows:
            LOGGER.info("Using cached Yahoo Finance bars for symbol=%s rows=%s", symbol, len(cached_rows))
            payload.extend(cached_rows)
            symbols_with_data += 1
            continue

        rows, fetch_warning = _download_symbol_rows_with_retry(
            symbol=symbol,
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            session=yahoo_session,
        )

        if fetch_warning:
            warnings.append(fetch_warning)

        if not rows:
            seed_rows = seed_rows_by_symbol.get(symbol, [])
            if seed_rows:
                warnings.append(
                    f"Yahoo unavailable for {ticker}; using CSV seed fallback rows={len(seed_rows)}"
                )
                rows = _clone_rows_for_symbol(symbol, seed_rows)
                used_seed_fallback = True

        if rows:
            symbols_with_data += 1
            payload.extend(rows)
            cache_symbols[symbol] = rows
            _save_symbol_cache(cache_file, cache_payload)
        else:
            symbols_without_data += 1

        _sleep_randomized_fetch_delay()

    source = "yahoo-finance-real"
    if used_seed_fallback and symbols_with_data > 0:
        source = "yahoo-plus-csv-seed"
    elif used_seed_fallback:
        source = "csv-seed"

    payload.sort(key=lambda item: (item["symbol"], item["tradeDate"]))

    if not payload:
        warnings.append("No historical rows available from Yahoo or CSV seed sources")

    stats = {
        "source": source,
        "symbolsRequested": len(symbols),
        "symbolsWithData": symbols_with_data,
        "symbolsWithoutData": symbols_without_data,
    }
    return payload, stats, warnings


def _chunked(items: list[dict[str, Any]], chunk_size: int) -> list[list[dict[str, Any]]]:
    if chunk_size <= 0:
        return [items]

    return [items[idx: idx + chunk_size] for idx in range(0, len(items), chunk_size)]


def _post_json(url: str, payload: Any) -> tuple[int, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = url_request.Request(
        url=url,
        method="POST",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:
        with url_request.urlopen(req, timeout=60) as response:
            raw_response = response.read().decode("utf-8", errors="replace")
            return response.getcode(), _safe_parse_json(raw_response)
    except url_error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, _safe_parse_json(body)


def _safe_parse_json(raw_text: str) -> Any:
    if not raw_text:
        return {}
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return {"raw": raw_text}


def _resolve_symbols() -> list[str]:
    override = os.getenv("HISTORICAL_INGEST_SYMBOLS", "").strip()
    if not override:
        return list(EGX30_SYMBOLS)

    symbols: list[str] = []
    for token in override.split(","):
        symbol = token.strip().upper()
        if symbol:
            symbols.append(symbol)

    return symbols or list(EGX30_SYMBOLS)


def _to_yahoo_ticker(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if normalized.endswith(YAHOO_SUFFIX):
        return normalized
    return f"{normalized}{YAHOO_SUFFIX}"


def _download_symbol_rows_with_retry(
    symbol: str,
    ticker: str,
    start_date: date,
    end_date: date,
    session: requests.Session,
) -> tuple[list[dict[str, Any]], str | None]:
    last_exception: Exception | None = None

    for attempt in range(1, YAHOO_MAX_RETRIES + 1):
        try:
            raw = yf.download(
                tickers=ticker,
                start=start_date.isoformat(),
                end=end_date.isoformat(),
                interval="1d",
                auto_adjust=False,
                actions=False,
                group_by="ticker",
                progress=False,
                threads=False,
                session=session,
            )

            normalized = _normalize_ticker_frame(_extract_ticker_frame(raw, ticker))
            if normalized.empty:
                if attempt < YAHOO_MAX_RETRIES:
                    time.sleep(YAHOO_RATE_LIMIT_BACKOFF_SECONDS)
                    continue
                return [], f"No Yahoo Finance bars for {ticker}"

            return _rows_from_frame(symbol, normalized), None
        except Exception as exc:  # noqa: BLE001
            last_exception = exc

            if _is_rate_limit_error(exc) and attempt < YAHOO_MAX_RETRIES:
                LOGGER.warning(
                    "Yahoo rate-limit detected for symbol=%s ticker=%s attempt=%s/%s, backing off %ss",
                    symbol,
                    ticker,
                    attempt,
                    YAHOO_MAX_RETRIES,
                    int(YAHOO_RATE_LIMIT_BACKOFF_SECONDS),
                )
                time.sleep(YAHOO_RATE_LIMIT_BACKOFF_SECONDS)
                continue

            if _is_rate_limit_error(exc):
                return [], f"Yahoo rate-limited for {ticker}; falling back to local seed data"

            if attempt < YAHOO_MAX_RETRIES:
                time.sleep(2.0)
                continue

    return [], f"Yahoo Finance fetch failed for {ticker}: {last_exception}"


def _rows_from_frame(symbol: str, frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for idx, row in frame.iterrows():
        trade_date = _coerce_trade_date(idx)
        if trade_date is None:
            continue

        rows.append(
            {
                "symbol": symbol,
                "tradeDate": trade_date.isoformat(),
                "openPrice": round(float(row["Open"]), 4),
                "highPrice": round(float(row["High"]), 4),
                "lowPrice": round(float(row["Low"]), 4),
                "closePrice": round(float(row["Close"]), 4),
                "volume": int(max(0.0, float(row["Volume"]))),
                "halted": False,
            }
        )

    return rows


def _is_rate_limit_error(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    return (
        "ratelimit" in name
        or "rate limit" in message
        or "too many requests" in message
        or "429" in message
    )


def _build_yahoo_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": YAHOO_BROWSER_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
        }
    )
    return session


def _sleep_randomized_fetch_delay() -> None:
    delay = random.uniform(YAHOO_MIN_DELAY_SECONDS, YAHOO_MAX_DELAY_SECONDS)
    time.sleep(delay)


def _cache_file_path() -> Path:
    raw_path = os.getenv("HISTORICAL_INGEST_CACHE_FILE", DEFAULT_CACHE_FILE).strip()
    if not raw_path:
        raw_path = DEFAULT_CACHE_FILE
    return Path(raw_path)


def _load_symbol_cache(cache_file: Path) -> dict[str, Any]:
    if not cache_file.exists():
        return {"symbols": {}}

    try:
        raw = cache_file.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except Exception:  # noqa: BLE001
        LOGGER.warning("Historical cache unreadable at %s; starting new cache", cache_file)
        return {"symbols": {}}

    if not isinstance(parsed, dict):
        return {"symbols": {}}

    symbols = parsed.get("symbols")
    if not isinstance(symbols, dict):
        parsed["symbols"] = {}

    return parsed


def _save_symbol_cache(cache_file: Path, payload: dict[str, Any]) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(payload), encoding="utf-8")


def _read_cached_symbol_rows(cache_symbols: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
    rows = cache_symbols.get(symbol)
    if not isinstance(rows, list):
        return []

    normalized_rows: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue

        required = {"tradeDate", "openPrice", "highPrice", "lowPrice", "closePrice", "volume"}
        if not required.issubset(set(item.keys())):
            continue

        normalized_rows.append(
            {
                "symbol": symbol,
                "tradeDate": str(item["tradeDate"]),
                "openPrice": _safe_float(item["openPrice"]),
                "highPrice": _safe_float(item["highPrice"]),
                "lowPrice": _safe_float(item["lowPrice"]),
                "closePrice": _safe_float(item["closePrice"]),
                "volume": _safe_int(item["volume"]),
                "halted": bool(item.get("halted", False)),
            }
        )

    return normalized_rows


def _load_seed_rows(seed_file: Path, warnings: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not seed_file.exists():
        warnings.append(f"CSV seed file not found: {seed_file}")
        return {}

    grouped: dict[str, list[dict[str, Any]]] = {}

    try:
        with seed_file.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                symbol = (row.get("symbol") or "").strip().upper()
                trade_date = (row.get("trade_date") or "").strip()
                if not symbol or not trade_date:
                    continue

                grouped.setdefault(symbol, []).append(
                    {
                        "symbol": symbol,
                        "tradeDate": trade_date,
                        "openPrice": _safe_float(row.get("open_price")),
                        "highPrice": _safe_float(row.get("high_price")),
                        "lowPrice": _safe_float(row.get("low_price")),
                        "closePrice": _safe_float(row.get("close_price")),
                        "volume": _safe_int(row.get("volume")),
                        "halted": False,
                    }
                )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Failed to read CSV seed file {seed_file}: {exc}")
        return {}

    return grouped


def _clone_rows_for_symbol(symbol: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cloned: list[dict[str, Any]] = []
    for row in rows:
        cloned.append(
            {
                "symbol": symbol,
                "tradeDate": str(row.get("tradeDate")),
                "openPrice": _safe_float(row.get("openPrice")),
                "highPrice": _safe_float(row.get("highPrice")),
                "lowPrice": _safe_float(row.get("lowPrice")),
                "closePrice": _safe_float(row.get("closePrice")),
                "volume": _safe_int(row.get("volume")),
                "halted": bool(row.get("halted", False)),
            }
        )
    return cloned


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(float(value))
    except Exception:  # noqa: BLE001
        return 0


def _extract_ticker_frame(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        level0 = set(str(value) for value in raw.columns.get_level_values(0))
        level1 = set(str(value) for value in raw.columns.get_level_values(1))

        if ticker in level0:
            frame = raw[ticker].copy()
        elif ticker in level1:
            frame = raw.xs(ticker, axis=1, level=1).copy()
        else:
            return pd.DataFrame()
    else:
        frame = raw.copy()

    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = [str(column[-1]) for column in frame.columns]

    return frame


def _normalize_ticker_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()

    columns = {str(col).strip().lower(): col for col in frame.columns}
    open_col = _pick_column(columns, ["open"])
    high_col = _pick_column(columns, ["high"])
    low_col = _pick_column(columns, ["low"])
    close_col = _pick_column(columns, ["close", "adj close", "adj_close"])
    volume_col = _pick_column(columns, ["volume"])

    if close_col is None:
        return pd.DataFrame()

    normalized = pd.DataFrame(index=frame.index)
    normalized["Open"] = pd.to_numeric(frame[open_col], errors="coerce") if open_col is not None else pd.to_numeric(frame[close_col], errors="coerce")
    normalized["High"] = pd.to_numeric(frame[high_col], errors="coerce") if high_col is not None else pd.to_numeric(frame[close_col], errors="coerce")
    normalized["Low"] = pd.to_numeric(frame[low_col], errors="coerce") if low_col is not None else pd.to_numeric(frame[close_col], errors="coerce")
    normalized["Close"] = pd.to_numeric(frame[close_col], errors="coerce")
    if volume_col is not None:
        normalized["Volume"] = pd.to_numeric(frame[volume_col], errors="coerce")
    else:
        normalized["Volume"] = 0.0

    normalized = normalized.dropna(subset=["Close"])
    if normalized.empty:
        return normalized

    normalized["Open"] = normalized["Open"].fillna(normalized["Close"])
    normalized["High"] = normalized["High"].fillna(normalized["Close"])
    normalized["Low"] = normalized["Low"].fillna(normalized["Close"])

    normalized["High"] = normalized[["Open", "High", "Low", "Close"]].max(axis=1)
    normalized["Low"] = normalized[["Open", "High", "Low", "Close"]].min(axis=1)
    normalized["Volume"] = normalized["Volume"].fillna(0.0).clip(lower=0.0)

    normalized = normalized.sort_index()
    return normalized


def _pick_column(columns: dict[str, Any], candidates: list[str]) -> Any:
    for candidate in candidates:
        if candidate in columns:
            return columns[candidate]
    return None


def _coerce_trade_date(value: Any) -> date | None:
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.date()

    try:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.date()
    except Exception:  # noqa: BLE001
        return None
