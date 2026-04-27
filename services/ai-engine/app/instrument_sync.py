from __future__ import annotations

import csv
import importlib
import json
import logging
import os
import random
import re
import string
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error as url_error
from urllib import request as url_request

import requests
import yfinance as yf

from tvDatafeed import TvDatafeed, Interval

from .data_pipeline import DEFAULT_SECTOR_MAP, EGX30_SYMBOLS

LOGGER = logging.getLogger(__name__)
DEFAULT_CORE_BACKEND_URL = "http://core-backend:8081"
DEFAULT_CORE_BULK_PATH = "/api/core/instruments/bulk"
DEFAULT_CORE_CATALOG_PATH = "/api/core/instruments/ids"
DEFAULT_SECTOR = "Financial Services"
DEFAULT_SEED_CSV_FILE = Path(__file__).resolve().parent / "data" / "egx30_snapshot.csv"
YAHOO_SUFFIX = ".CA"
SYMBOL_MAX_LENGTH = 16
CORE_CATALOG_CACHE_TTL_SECONDS = float(os.getenv("CORE_CATALOG_CACHE_TTL_SECONDS", "300"))
YAHOO_MIN_DELAY_SECONDS = 2.0
YAHOO_MAX_DELAY_SECONDS = 5.0
YAHOO_RATE_LIMIT_BACKOFF_SECONDS = 5.0
YAHOO_MAX_RETRIES = 3
YAHOO_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

EGX30_FALLBACK_METADATA: dict[str, dict[str, str]] = {
    "COMI": {"name": "Commercial International Bank", "sector": "Banks"},
    "HRHO": {"name": "EFG Holding", "sector": "Financial Services"},
    "SWDY": {"name": "Elsewedy Electric", "sector": "Industrials"},
    "ETEL": {"name": "Telecom Egypt", "sector": "Telecommunications"},
    "EFIH": {"name": "E-Finance", "sector": "Technology"},
    "ABUK": {"name": "Abu Qir Fertilizers", "sector": "Materials"},
    "FWRY": {"name": "Fawry", "sector": "Technology"},
    "PHDC": {"name": "Palm Hills Development", "sector": "Real Estate"},
    "TMGH": {"name": "Talaat Moustafa Group", "sector": "Real Estate"},
    "ORWE": {"name": "Oriental Weavers", "sector": "Consumer Discretionary"},
    "EAST": {"name": "Eastern Company", "sector": "Consumer Staples"},
    "AMOC": {"name": "Alexandria Mineral Oils", "sector": "Energy"},
    "MFPC": {"name": "Misr Fertilizers Production", "sector": "Materials"},
    "SKPC": {"name": "Sidi Kerir Petrochemicals", "sector": "Materials"},
    "CCAP": {"name": "Citadel Capital", "sector": "Financial Services"},
    "HELI": {"name": "Heliopolis Housing", "sector": "Real Estate"},
    "PACH": {"name": "Paint and Chemicals Industries", "sector": "Materials"},
    "EKHO": {"name": "Egypt Kuwait Holding", "sector": "Industrials"},
    "MICH": {"name": "Misr Chemical Industries", "sector": "Materials"},
    "ALCN": {"name": "Alexandria Containers", "sector": "Industrials"},
    "ESRS": {"name": "Ezz Steel", "sector": "Materials"},
    "JUFO": {"name": "Juhayna Food Industries", "sector": "Consumer Staples"},
    "DOMT": {"name": "Domty", "sector": "Consumer Staples"},
    "GDWA": {"name": "Gadwa", "sector": "Financial Services"},
    "CIEB": {"name": "Credit Agricole Egypt", "sector": "Banks"},
    "AUTO": {"name": "GB Corp", "sector": "Consumer Discretionary"},
    "BTFH": {"name": "Beltone Holding", "sector": "Financial Services"},
    "OBRI": {"name": "Obour Land", "sector": "Consumer Staples"},
    "RAYA": {"name": "Raya Holding", "sector": "Technology"},
    "CLHO": {"name": "Cleopatra Hospitals", "sector": "Healthcare"},
}

for _base_symbol, _metadata in list(EGX30_FALLBACK_METADATA.items()):
    EGX30_FALLBACK_METADATA[f"{_base_symbol}{YAHOO_SUFFIX}"] = _metadata


_core_catalog_cache: dict[str, Any] = {
    "catalogUrl": "",
    "fetchedAt": 0.0,
    "items": [],
}

SECTOR_CODE_TO_NAME = {
    "BANKS": "Banks",
    "FIN_SERV": "Financial Services",
    "FINANCIAL_SERVICES": "Financial Services",
    "INDUSTRIALS": "Industrials",
    "REAL_ESTATE": "Real Estate",
    "TELECOM": "Telecommunications",
    "ENERGY": "Energy",
    "CONSUMER": "Consumer Staples",
    "CONSUMER_NON_CYCLICAL": "Consumer Staples",
    "CONSUMER_CYCLICAL": "Consumer Discretionary",
    "HEALTHCARE": "Healthcare",
    "MATERIALS": "Materials",
    "TRANSPORT": "Transportation",
    "UTILITIES": "Utilities",
    "TECHNOLOGY": "Technology",
}


@dataclass(frozen=True)
class ExchangeInstrument:
    symbol: str
    name: str
    sector: str


def sync_live_instruments_to_core() -> dict[str, Any]:
    instruments, source, warnings = fetch_active_exchange_instruments()
    payload = [
        {
            "symbol": instrument.symbol,
            "name": instrument.name,
            "sector": instrument.sector,
        }
        for instrument in instruments
    ]

    core_base_url = os.getenv("CORE_BACKEND_URL", DEFAULT_CORE_BACKEND_URL).rstrip("/")
    core_bulk_url = f"{core_base_url}{DEFAULT_CORE_BULK_PATH}"
    status_code, core_response = _post_json(core_bulk_url, payload)

    return {
        "status": "SUCCESS",
        "source": source,
        "instrumentCount": len(payload),
        "coreBulkUrl": core_bulk_url,
        "coreStatusCode": status_code,
        "coreResponse": core_response,
        "warnings": warnings,
    }


def fetch_core_instrument_catalog(force_refresh: bool = False) -> dict[str, Any]:
    core_base_url = os.getenv("CORE_BACKEND_URL", DEFAULT_CORE_BACKEND_URL).rstrip("/")
    catalog_url = f"{core_base_url}{DEFAULT_CORE_CATALOG_PATH}"

    now = time.time()
    cached_items = _core_catalog_cache.get("items")
    cached_at = float(_core_catalog_cache.get("fetchedAt") or 0.0)
    cached_url = _core_catalog_cache.get("catalogUrl")

    if (
        not force_refresh
        and isinstance(cached_items, list)
        and cached_items
        and cached_url == catalog_url
        and (now - cached_at) < CORE_CATALOG_CACHE_TTL_SECONDS
    ):
        return {
            "catalogUrl": catalog_url,
            "cached": True,
            "instrumentCount": len(cached_items),
            "items": list(cached_items),
        }

    status_code, payload = _get_json(catalog_url)
    if not isinstance(payload, list):
        raise RuntimeError("Core instrument catalog must return a JSON array")

    by_symbol: dict[str, dict[str, Any]] = {}
    for raw_item in payload:
        if not isinstance(raw_item, dict):
            continue

        symbol = _normalize_symbol(str(raw_item.get("symbol") or ""))
        instrument_id = _coerce_positive_int(
            raw_item.get("instrumentId")
            or raw_item.get("instrument_id")
            or raw_item.get("id")
        )

        if symbol is None or instrument_id is None:
            continue

        candidate = {
            "instrumentId": instrument_id,
            "symbol": symbol,
            "name": str(raw_item.get("name") or symbol)[:255],
            "sectorCode": str(raw_item.get("sectorCode") or raw_item.get("sector_code") or "")[:64],
        }

        existing = by_symbol.get(symbol)
        if existing is None or candidate["instrumentId"] < existing["instrumentId"]:
            by_symbol[symbol] = candidate

    normalized_items = sorted(by_symbol.values(), key=lambda item: item["symbol"])
    if not normalized_items:
        raise RuntimeError("Core instrument catalog returned no valid instrument entries")

    _core_catalog_cache["catalogUrl"] = catalog_url
    _core_catalog_cache["fetchedAt"] = time.time()
    _core_catalog_cache["items"] = normalized_items

    return {
        "catalogUrl": catalog_url,
        "cached": False,
        "statusCode": status_code,
        "instrumentCount": len(normalized_items),
        "items": list(normalized_items),
    }


def fetch_active_exchange_instruments() -> tuple[list[ExchangeInstrument], str, list[str]]:
    warnings: list[str] = []

    # Try TradingView first (direct EGX exchange data)
    tv_instruments = _discover_with_tradingview(warnings)
    if tv_instruments:
        return tv_instruments, "tradingview-egx30", warnings

    instruments = _discover_with_provider(warnings)
    if instruments:
        return instruments, "live-provider", warnings

    yahoo_instruments = _discover_with_yfinance(warnings)
    if yahoo_instruments:
        return yahoo_instruments, "yfinance-egx30", warnings

    warnings.append("Live provider discovery unavailable; CSV/hardcoded EGX30 fallback used")
    return _fallback_instruments(warnings), "fallback-egx30", warnings


def _discover_with_tradingview(warnings: list[str]) -> list[ExchangeInstrument]:
    """
    Discover EGX instruments using TradingView by probing each EGX30 symbol.

    TradingView has direct EGX exchange data, so this is more reliable
    than yfinance which has been rate-limiting EGX data.
    """
    discovered: dict[str, ExchangeInstrument] = {}

    try:
        tv = TvDatafeed()
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"TradingView init failed: {exc}")
        return []

    for symbol in EGX30_SYMBOLS:
        canonical_symbol = _normalize_symbol(symbol)
        if canonical_symbol is None:
            continue

        # Strip .CA suffix for TradingView
        tv_symbol = symbol.replace(".CA", "") if symbol.endswith(".CA") else symbol

        try:
            df = tv.get_hist(
                symbol=tv_symbol,
                exchange="EGX",
                interval=Interval.in_daily,
                n_bars=5,
            )

            if df is not None and not df.empty:
                metadata = EGX30_FALLBACK_METADATA.get(canonical_symbol, {})
                discovered[canonical_symbol] = ExchangeInstrument(
                    symbol=canonical_symbol,
                    name=str(
                        metadata.get("name")
                        or canonical_symbol
                    )[:255],
                    sector=_resolve_sector_name(canonical_symbol, None),
                )
                LOGGER.info("TradingView probe OK for symbol=%s (tv_symbol=%s)", canonical_symbol, tv_symbol)
            else:
                LOGGER.debug("TradingView no data for tv_symbol=%s", tv_symbol)

        except Exception as exc:  # noqa: BLE001
            warnings.append(f"TradingView probe failed for {tv_symbol}: {exc}")

        # Anti-ban throttling between symbol probes
        time.sleep(1.5)

    return sorted(discovered.values(), key=lambda item: item.symbol)


def _discover_with_yfinance(warnings: list[str]) -> list[ExchangeInstrument]:
    session = _build_yahoo_session()
    seed_metadata = _load_seed_metadata(warnings)
    discovered: dict[str, ExchangeInstrument] = {}

    for symbol in EGX30_SYMBOLS:
        canonical_symbol = _normalize_symbol(symbol)
        if canonical_symbol is None:
            continue

        ticker = _to_yahoo_ticker(canonical_symbol)
        LOGGER.info("Fetching Yahoo instrument probe for symbol=%s ticker=%s", canonical_symbol, ticker)

        available, warning = _probe_ticker_with_retry(symbol=canonical_symbol, ticker=ticker, session=session)
        if warning:
            warnings.append(warning)

        if available:
            metadata = seed_metadata.get(canonical_symbol, {})
            discovered[canonical_symbol] = ExchangeInstrument(
                symbol=canonical_symbol,
                name=str(
                    metadata.get("name")
                    or EGX30_FALLBACK_METADATA.get(canonical_symbol, {}).get("name")
                    or canonical_symbol
                )[:255],
                sector=_resolve_sector_name(canonical_symbol, str(metadata.get("sector") or "")),
            )

        _sleep_randomized_fetch_delay()

    return sorted(discovered.values(), key=lambda item: item.symbol)


def _probe_ticker_with_retry(
    symbol: str,
    ticker: str,
    session: requests.Session,
) -> tuple[bool, str | None]:
    last_exception: Exception | None = None

    for attempt in range(1, YAHOO_MAX_RETRIES + 1):
        try:
            frame = yf.download(
                tickers=ticker,
                period="5d",
                interval="1d",
                auto_adjust=False,
                actions=False,
                group_by="ticker",
                progress=False,
                threads=False,
                session=session,
            )

            if frame is None or frame.empty:
                return False, f"No Yahoo snapshot data for {ticker}"

            return True, None
        except Exception as exc:  # noqa: BLE001
            last_exception = exc
            if _is_rate_limit_error(exc):
                if attempt < YAHOO_MAX_RETRIES:
                    LOGGER.warning(
                        "Yahoo rate-limit during instrument probe for symbol=%s ticker=%s attempt=%s/%s",
                        symbol,
                        ticker,
                        attempt,
                        YAHOO_MAX_RETRIES,
                    )
                    time.sleep(YAHOO_RATE_LIMIT_BACKOFF_SECONDS)
                    continue
                return False, f"Yahoo rate-limited for {ticker}; continuing with fallback"

            if attempt < YAHOO_MAX_RETRIES:
                time.sleep(1.0)
                continue

    return False, f"Yahoo probe failed for {ticker}: {last_exception}"


def _discover_with_provider(warnings: list[str]) -> list[ExchangeInstrument]:
    instruments: dict[str, ExchangeInstrument] = {}

    for client in _build_exchange_clients(warnings):
        listed = _extract_with_listing_methods(client, warnings)
        if not listed:
            listed = _extract_with_search_method(client, warnings)

        for item in listed:
            instruments[item.symbol] = item

        if len(instruments) >= 40:
            break

    return sorted(instruments.values(), key=lambda item: item.symbol)


def _build_exchange_clients(warnings: list[str]) -> list[Any]:
    clients: list[Any] = []

    module_names = ["tvDatafeed", "egxpy"]
    for module_name in module_names:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Module import failed for {module_name}: {exc}")
            continue

        for class_name in ("TvDatafeedLive", "TvDatafeed"):
            candidate = getattr(module, class_name, None)
            if not callable(candidate):
                continue

            try:
                clients.append(candidate())
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Provider init failed for {module_name}.{class_name}: {exc}")

    return clients


def _extract_with_listing_methods(client: Any, warnings: list[str]) -> list[ExchangeInstrument]:
    listing_methods = [
        "get_all_symbols",
        "get_symbols",
        "get_stocks",
        "list_symbols",
        "list_instruments",
    ]

    for method_name in listing_methods:
        method = getattr(client, method_name, None)
        if not callable(method):
            continue

        for kwargs in ({"exchange": "EGX"}, {"market": "EGX"}, {}):
            try:
                raw = method(**kwargs)
            except TypeError:
                continue
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{client.__class__.__name__}.{method_name} failed: {exc}")
                continue

            instruments = _normalize_raw_instruments(raw)
            if instruments:
                return instruments

        for args in (("EGX",), ()):  # positional call fallbacks
            try:
                raw = method(*args)
            except TypeError:
                continue
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{client.__class__.__name__}.{method_name} failed: {exc}")
                continue

            instruments = _normalize_raw_instruments(raw)
            if instruments:
                return instruments

    return []


def _extract_with_search_method(client: Any, warnings: list[str]) -> list[ExchangeInstrument]:
    search = getattr(client, "search_symbol", None)
    if not callable(search):
        return []

    probe = _try_search_call(search, "EGX", warnings)
    probe_items = _normalize_raw_instruments(probe)
    if not probe_items:
        return []

    collected: dict[str, ExchangeInstrument] = {}
    for item in probe_items:
        collected[item.symbol] = item

    for token in string.ascii_uppercase:
        raw = _try_search_call(search, token, warnings)
        for item in _normalize_raw_instruments(raw):
            collected[item.symbol] = item

        if len(collected) >= 250:
            break

    return sorted(collected.values(), key=lambda item: item.symbol)


def _try_search_call(search_method: Any, token: str, warnings: list[str]) -> Any:
    call_shapes = [
        {"text": token, "exchange": "EGX"},
        {"symbol": token, "exchange": "EGX"},
        {"text": token},
    ]
    for kwargs in call_shapes:
        try:
            return search_method(**kwargs)
        except TypeError:
            continue
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"search_symbol failed for token {token}: {exc}")
            return []

    for args in ((token, "EGX"), (token,)):
        try:
            return search_method(*args)
        except TypeError:
            continue
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"search_symbol failed for token {token}: {exc}")
            return []

    return []


def _normalize_raw_instruments(raw: Any) -> list[ExchangeInstrument]:
    rows = _raw_to_rows(raw)
    if not rows:
        return []

    instruments: dict[str, ExchangeInstrument] = {}
    for row in rows:
        if isinstance(row, str):
            symbol = _normalize_symbol(row)
            if symbol is None:
                continue

            metadata = EGX30_FALLBACK_METADATA.get(symbol, {})

            instruments[symbol] = ExchangeInstrument(
                symbol=symbol,
                name=metadata.get("name", symbol),
                sector=_resolve_sector_name(symbol, None),
            )
            continue

        if not isinstance(row, dict):
            continue

        symbol = _first_non_blank(row, "symbol", "ticker", "code", "pro_name", "full_name")
        symbol = _normalize_symbol(symbol)
        if symbol is None:
            continue

        exchange = _first_non_blank(row, "exchange", "market", "exchangeName")
        if exchange and "EGX" not in exchange.upper():
            continue

        name = _first_non_blank(row, "name", "description", "display_name", "short_name") or symbol
        sector = _resolve_sector_name(
            symbol,
            _first_non_blank(row, "sector", "sector_name", "industry"),
        )

        instruments[symbol] = ExchangeInstrument(
            symbol=symbol,
            name=name.strip()[:255],
            sector=sector,
        )

    return sorted(instruments.values(), key=lambda item: item.symbol)


def _raw_to_rows(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("data", "symbols", "instruments", "results", "items"):
            value = raw.get(key)
            if isinstance(value, list):
                return value
        return [raw]

    if hasattr(raw, "to_dict"):
        try:
            as_dict = raw.to_dict(orient="records")
            if isinstance(as_dict, list):
                return as_dict
        except TypeError:
            pass
        except Exception:  # noqa: BLE001
            return []

    return []


def _normalize_symbol(raw: str | None) -> str | None:
    base_symbol = _base_symbol(raw)
    if base_symbol is None:
        return None

    canonical = f"{base_symbol}{YAHOO_SUFFIX}"
    return canonical[:SYMBOL_MAX_LENGTH]


def _base_symbol(raw: str | None) -> str | None:
    if raw is None:
        return None

    symbol = raw.strip().upper()
    if not symbol:
        return None

    if ":" in symbol:
        symbol = symbol.split(":")[-1]
    if symbol.endswith(YAHOO_SUFFIX):
        symbol = symbol[: -len(YAHOO_SUFFIX)]
    if "." in symbol:
        symbol = symbol.split(".")[0]

    symbol = re.sub(r"[^A-Z0-9_-]", "", symbol)
    if not symbol:
        return None

    return symbol[:SYMBOL_MAX_LENGTH]


def _first_non_blank(row: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _fallback_instruments(warnings: list[str]) -> list[ExchangeInstrument]:
    seed_metadata = _load_seed_metadata(warnings)

    fallback: list[ExchangeInstrument] = []
    for symbol in EGX30_SYMBOLS:
        canonical_symbol = _normalize_symbol(symbol)
        if canonical_symbol is None:
            continue

        metadata = seed_metadata.get(canonical_symbol, {})
        fallback.append(
            ExchangeInstrument(
                symbol=canonical_symbol,
                name=str(
                    metadata.get("name")
                    or EGX30_FALLBACK_METADATA.get(canonical_symbol, {}).get("name")
                    or canonical_symbol
                )[:255],
                sector=_resolve_sector_name(canonical_symbol, str(metadata.get("sector") or "")),
            )
        )

    return fallback


def _resolve_sector_name(symbol: str, raw_sector: str | None) -> str:
    if raw_sector:
        cleaned = raw_sector.strip()
        if cleaned and cleaned.upper() not in {"UNKNOWN", "N/A", "UNCLASSIFIED", "NULL"}:
            return cleaned[:64]

    metadata_sector = EGX30_FALLBACK_METADATA.get(symbol, {}).get("sector")
    if metadata_sector:
        return metadata_sector[:64]

    base_symbol = _base_symbol(symbol)
    mapped_code = DEFAULT_SECTOR_MAP.get(base_symbol) if base_symbol else None
    if mapped_code:
        resolved = SECTOR_CODE_TO_NAME.get(mapped_code.upper(), mapped_code.replace("_", " ").title())
        return resolved[:64]

    return DEFAULT_SECTOR


def _to_yahoo_ticker(symbol: str) -> str:
    normalized = _normalize_symbol(symbol)
    if normalized is None:
        normalized = symbol.strip().upper()
    if normalized.endswith(YAHOO_SUFFIX):
        return normalized
    return f"{normalized}{YAHOO_SUFFIX}"


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


def _is_rate_limit_error(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    return (
        "ratelimit" in name
        or "rate limit" in message
        or "too many requests" in message
        or "429" in message
    )


def _load_seed_metadata(warnings: list[str]) -> dict[str, dict[str, str]]:
    if not DEFAULT_SEED_CSV_FILE.exists():
        warnings.append(f"Instrument seed CSV not found: {DEFAULT_SEED_CSV_FILE}")
        return {}

    metadata: dict[str, dict[str, str]] = {}

    try:
        with DEFAULT_SEED_CSV_FILE.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                symbol = _normalize_symbol(row.get("symbol"))
                if not symbol:
                    continue

                name = (row.get("name") or "").strip()
                sector = (row.get("sector") or "").strip()
                metadata[symbol] = {
                    "name": name,
                    "sector": sector,
                }
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Failed reading instrument seed CSV: {exc}")
        return {}

    return metadata


def _coerce_positive_int(raw: Any) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None

    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return None

    if parsed <= 0:
        return None

    return parsed


def _get_json(url: str) -> tuple[int, Any]:
    req = url_request.Request(
        url=url,
        method="GET",
        headers={
            "Accept": "application/json",
        },
    )

    try:
        with url_request.urlopen(req, timeout=20) as response:
            raw_response = response.read().decode("utf-8", errors="replace")
            parsed = _safe_parse_json(raw_response)
            return response.getcode(), parsed
    except url_error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Core catalog fetch failed with HTTP {exc.code}: {body}") from exc
    except url_error.URLError as exc:
        raise RuntimeError(f"Core catalog fetch transport failure: {exc}") from exc


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
        with url_request.urlopen(req, timeout=40) as response:
            raw_response = response.read().decode("utf-8", errors="replace")
            parsed = _safe_parse_json(raw_response)
            return response.getcode(), parsed
    except url_error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Core bulk sync failed with HTTP {exc.code}: {body}") from exc
    except url_error.URLError as exc:
        raise RuntimeError(f"Core bulk sync transport failure: {exc}") from exc


def _safe_parse_json(raw_text: str) -> Any:
    if not raw_text:
        return {}
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return {"raw": raw_text}
