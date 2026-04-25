from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from app.data_pipeline import EGX30_SYMBOL_TO_CANONICAL, canonicalize_symbol, to_base_symbol

LOGGER = logging.getLogger("data_seeder")
DEFAULT_LOOKBACK_YEARS = 10
DEFAULT_DELAY_SECONDS = 0.25
DEFAULT_OUTPUT_DIR = Path("/app/data/historical")
MIN_EXPECTED_ROWS = 400
EODHD_BASE_URL = "https://eodhd.com"
EODHD_TOKEN_ENV_VAR = "69e67350a20f86.57807831"
EODHD_REQUEST_TIMEOUT_SECONDS = 30
EODHD_MAX_RETRIES = 3
EODHD_RETRY_DELAY_SECONDS = 1.0
API_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed 10 years of EGX30 historical OHLCV as per-symbol CSV files."
    )
    parser.add_argument("--years", type=int, default=DEFAULT_LOOKBACK_YEARS)
    parser.add_argument("--output-dir", type=str, default=os.getenv("HISTORICAL_DATA_DIR", str(DEFAULT_OUTPUT_DIR)))
    parser.add_argument("--delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--if-empty", action="store_true", help="Skip seeding if target directory already has CSV files")
    return parser.parse_args()


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": API_USER_AGENT,
            "Accept": "application/json",
            "Connection": "keep-alive",
        }
    )
    return session


def ticker_candidates(canonical_symbol: str) -> list[str]:
    base_symbol = to_base_symbol(canonical_symbol)
    if base_symbol is None:
        return []

    candidates = [
        f"{base_symbol}.CA",
        f"{base_symbol}.CAI",
        f"{base_symbol}.EGX",
        base_symbol,
    ]

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)

    return deduped


def download_symbol_history(
    canonical_symbol: str,
    start_date: date,
    end_date: date,
    session: requests.Session,
    api_token: str,
) -> tuple[pd.DataFrame | None, str | None, str | None]:
    last_error: str | None = None

    for ticker in ticker_candidates(canonical_symbol):
        for attempt in range(1, EODHD_MAX_RETRIES + 1):
            try:
                endpoint = f"{EODHD_BASE_URL}/api/eod/{ticker}"
                response = session.get(
                    endpoint,
                    params={
                        "api_token": api_token,
                        "fmt": "json",
                        "from": start_date.isoformat(),
                        "to": end_date.isoformat(),
                    },
                    timeout=EODHD_REQUEST_TIMEOUT_SECONDS,
                )

                if response.status_code == 404:
                    last_error = f"Ticker {ticker} returned no data (404)"
                    break

                if response.status_code >= 400:
                    body = response.text[:200]
                    if _looks_like_unknown_symbol_error(body):
                        last_error = f"Ticker {ticker} returned no data"
                        break
                    raise RuntimeError(f"HTTP {response.status_code}: {body}")

                payload: Any
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise RuntimeError("Invalid JSON response") from exc

                error_message = _extract_error_message(payload)
                if error_message:
                    if _looks_like_unknown_symbol_error(error_message):
                        last_error = f"Ticker {ticker} returned no data"
                        break
                    raise RuntimeError(error_message)

                bars = _extract_bars(payload)
                normalized = normalize_eodhd_bars(bars, canonical_symbol)
                if normalized.empty:
                    last_error = f"Ticker {ticker} returned no valid rows"
                    break

                return normalized, ticker, None
            except Exception as exc:  # noqa: BLE001
                last_error = f"Ticker {ticker} failed: {exc}"
                if attempt < EODHD_MAX_RETRIES:
                    time.sleep(EODHD_RETRY_DELAY_SECONDS)
                    continue
                break

    return None, None, last_error


def normalize_eodhd_bars(bars: list[dict[str, Any]], canonical_symbol: str) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame()

    raw = pd.DataFrame(bars)
    if raw.empty:
        return pd.DataFrame()

    column_map = {str(column).strip().lower(): column for column in raw.columns}
    date_col = column_map.get("date")
    open_col = column_map.get("open")
    high_col = column_map.get("high")
    low_col = column_map.get("low")
    close_col = column_map.get("close")
    volume_col = column_map.get("volume")

    if date_col is None or close_col is None:
        return pd.DataFrame()

    output = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(raw[date_col], errors="coerce"),
            "open": pd.to_numeric(raw[open_col], errors="coerce") if open_col is not None else pd.NA,
            "high": pd.to_numeric(raw[high_col], errors="coerce") if high_col is not None else pd.NA,
            "low": pd.to_numeric(raw[low_col], errors="coerce") if low_col is not None else pd.NA,
            "close": pd.to_numeric(raw[close_col], errors="coerce"),
            "volume": pd.to_numeric(raw[volume_col], errors="coerce") if volume_col is not None else 0,
        }
    )

    output = output.dropna(subset=["trade_date", "close"])
    if output.empty:
        return pd.DataFrame()

    output["open"] = output["open"].fillna(output["close"])
    output["high"] = output["high"].fillna(output["close"])
    output["low"] = output["low"].fillna(output["close"])
    output["volume"] = output["volume"].fillna(0.0).clip(lower=0.0)

    ohlc = output[["open", "high", "low", "close"]]
    output["high"] = ohlc.max(axis=1)
    output["low"] = ohlc.min(axis=1)

    output = output.sort_values("trade_date")
    output = output.drop_duplicates(subset=["trade_date"], keep="last")

    output["symbol"] = canonical_symbol
    output["trade_date"] = output["trade_date"].dt.date.astype(str)

    return output[["symbol", "trade_date", "open", "high", "low", "close", "volume"]]


def _extract_error_message(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None

    for key in ("error", "message", "note", "status", "s"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            lowered = value.strip().lower()
            if lowered in {"ok", "success"}:
                continue
            return value.strip()

    return None


def _extract_bars(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]

    return []


def _looks_like_unknown_symbol_error(raw_text: str) -> bool:
    message = (raw_text or "").lower()
    return (
        "not found" in message
        or "no data" in message
        or "unknown symbol" in message
        or ("symbol" in message and "invalid" in message)
    )


def write_symbol_csv(output_dir: Path, canonical_symbol: str, frame: pd.DataFrame) -> Path:
    base_symbol = to_base_symbol(canonical_symbol) or canonical_symbol.replace(".CA", "")
    target_file = output_dir / f"{base_symbol}.csv"
    frame.to_csv(target_file, index=False)
    return target_file


def run_seeding(years: int, output_dir: Path, delay_seconds: float, if_empty: bool) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)

    if if_empty and any(output_dir.glob("*.csv")):
        LOGGER.info("Historical directory already contains CSV files. Skipping seeding: %s", output_dir)
        return 0

    if years < 1:
        raise ValueError("years must be >= 1")

    symbols = list(EGX30_SYMBOL_TO_CANONICAL.values())
    start_date = date.today() - timedelta(days=366 * years)
    end_date = date.today()
    api_token = os.getenv(EODHD_TOKEN_ENV_VAR, "").strip()
    if not api_token:
        raise ValueError(f"{EODHD_TOKEN_ENV_VAR} is not configured")

    session = build_session()

    seeded = 0
    failed = 0
    total_rows = 0

    for index, canonical in enumerate(symbols, start=1):
        canonical_symbol = canonicalize_symbol(canonical)
        if canonical_symbol is None:
            LOGGER.warning("Skipping unmapped symbol: %s", canonical)
            failed += 1
            continue

        LOGGER.info("[%s/%s] Seeding %s", index, len(symbols), canonical_symbol)
        frame, ticker_used, warning = download_symbol_history(
            canonical_symbol=canonical_symbol,
            start_date=start_date,
            end_date=end_date,
            session=session,
            api_token=api_token,
        )

        if frame is None or frame.empty:
            failed += 1
            LOGGER.warning("Failed to seed %s (%s)", canonical_symbol, warning or "no data")
        else:
            if len(frame.index) < MIN_EXPECTED_ROWS:
                LOGGER.warning(
                    "Seeded %s from %s with low row count (%s rows)",
                    canonical_symbol,
                    ticker_used,
                    len(frame.index),
                )
            path = write_symbol_csv(output_dir, canonical_symbol, frame)
            seeded += 1
            total_rows += len(frame.index)
            LOGGER.info("Saved %s rows for %s into %s", len(frame.index), canonical_symbol, path)

        if index < len(symbols):
            time.sleep(max(0.0, delay_seconds))

    LOGGER.info(
        "Seeder completed: seeded=%s failed=%s total_rows=%s directory=%s",
        seeded,
        failed,
        total_rows,
        output_dir,
    )

    return 0 if seeded > 0 else 1


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    args = parse_args()
    return run_seeding(
        years=args.years,
        output_dir=Path(args.output_dir),
        delay_seconds=args.delay_seconds,
        if_empty=bool(args.if_empty),
    )


if __name__ == "__main__":
    raise SystemExit(main())
