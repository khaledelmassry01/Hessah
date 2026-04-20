from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request

DEFAULT_CORE_BACKEND_URL = "http://core-backend:8081"
DEFAULT_PARAMETERS_PATH = "/api/core/model-performance/params"
DEFAULT_LOG_PATH = "/api/core/model-performance/log"


@dataclass(frozen=True)
class AdaptiveParameters:
    risk_free_rate: float
    covariance_shrinkage: float
    source: str
    sample_size: int


def resolve_adaptive_parameters(risk_level: str) -> tuple[AdaptiveParameters, list[str]]:
    warnings: list[str] = []
    defaults = _default_parameters(risk_level)

    core_base_url = os.getenv("CORE_BACKEND_URL", DEFAULT_CORE_BACKEND_URL).rstrip("/")
    query = url_parse.urlencode({"riskLevel": risk_level})
    url = f"{core_base_url}{DEFAULT_PARAMETERS_PATH}?{query}"

    try:
        status_code, payload = _get_json(url)
        if status_code < 200 or status_code >= 300 or not isinstance(payload, dict):
            warnings.append("Adaptive parameters unavailable from core; using defaults")
            return defaults, warnings

        risk_free_rate = _safe_float(payload.get("riskFreeRate"), defaults.risk_free_rate)
        covariance_shrinkage = _safe_float(payload.get("covarianceShrinkage"), defaults.covariance_shrinkage)
        source = str(payload.get("source") or defaults.source)
        sample_size = int(payload.get("sampleSize") or 0)

        return (
            AdaptiveParameters(
                risk_free_rate=max(0.0, min(1.0, risk_free_rate)),
                covariance_shrinkage=max(0.0, min(1.0, covariance_shrinkage)),
                source=source,
                sample_size=max(0, sample_size),
            ),
            warnings,
        )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Adaptive parameter lookup failed; using defaults ({exc})")
        return defaults, warnings


def log_model_performance(event: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    core_base_url = os.getenv("CORE_BACKEND_URL", DEFAULT_CORE_BACKEND_URL).rstrip("/")
    url = f"{core_base_url}{DEFAULT_LOG_PATH}"

    try:
        status_code, payload = _post_json(url, event)
        if status_code < 200 or status_code >= 300:
            warnings.append("Model performance log was rejected by core service")
        elif not isinstance(payload, dict):
            warnings.append("Model performance log returned unexpected response shape")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Model performance log failed: {exc}")

    return warnings


def _default_parameters(risk_level: str) -> AdaptiveParameters:
    normalized = (risk_level or "MEDIUM").strip().upper()
    if normalized == "LOW":
        return AdaptiveParameters(risk_free_rate=0.18, covariance_shrinkage=0.25, source="default", sample_size=0)
    if normalized == "HIGH":
        return AdaptiveParameters(risk_free_rate=0.28, covariance_shrinkage=0.05, source="default", sample_size=0)
    return AdaptiveParameters(risk_free_rate=0.23, covariance_shrinkage=0.12, source="default", sample_size=0)


def _get_json(url: str) -> tuple[int, Any]:
    req = url_request.Request(
        url=url,
        method="GET",
        headers={"Accept": "application/json"},
    )

    try:
        with url_request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.getcode(), _safe_parse_json(body)
    except url_error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, _safe_parse_json(body)


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
        with url_request.urlopen(req, timeout=30) as response:
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


def _safe_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return float(fallback)
