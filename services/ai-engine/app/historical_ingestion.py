from __future__ import annotations

import json
import os
from typing import Any
from urllib import error as url_error
from urllib import request as url_request

from .data_pipeline import (
    EGX30_CANONICAL_SYMBOLS,
    build_historical_market_data_payload,
    resolve_historical_data_dir,
)

DEFAULT_CORE_BACKEND_URL = "http://core-backend:8081"
DEFAULT_MARKET_DATA_BULK_PATH = "/api/core/market-data/bulk"
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_YEARS = 10


def ingest_historical_market_data_to_core(years: int = DEFAULT_YEARS) -> dict[str, Any]:
    payload, stats, warnings = fetch_historical_data(years=years)
    source = str(stats.get("source") or "local-csv")

    if not payload:
        return {
            "status": "FAILED",
            "source": source,
            "provider": "local-csv",
            "years": years,
            "symbolsRequested": stats.get("symbolsRequested", 0),
            "symbolsWithData": stats.get("symbolsWithData", 0),
            "rowsPrepared": 0,
            "rowsSynced": 0,
            "warnings": warnings + ["No historical CSV rows were prepared for ingestion"],
        }

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
        "provider": "local-csv",
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
        "historicalDataDir": str(resolve_historical_data_dir()),
        "warnings": warnings,
    }


def fetch_historical_data(years: int = DEFAULT_YEARS) -> tuple[list[dict[str, Any]], dict[str, int | str], list[str]]:
    if years < 1:
        raise ValueError("years must be >= 1")

    payload, source, warnings = build_historical_market_data_payload(years=years)

    symbols_present = {
        str(item.get("symbol") or "")
        for item in payload
        if isinstance(item, dict)
    }
    symbols_present.discard("")

    symbols_with_data = len(symbols_present)
    symbols_without_data = max(0, len(EGX30_CANONICAL_SYMBOLS) - symbols_with_data)

    stats: dict[str, int | str] = {
        "source": source,
        "symbolsRequested": len(EGX30_CANONICAL_SYMBOLS),
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
