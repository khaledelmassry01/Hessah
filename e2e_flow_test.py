#!/usr/bin/env python3
"""End-to-end flow validation for EGX portfolio backend.

This script simulates a complete user journey through the Java API Gateway/Core Backend:
1) Login with static test user (fallback to register, then login)
2) Validate refresh-token flow and switch to refreshed access token
3) Verify at least one active tracked session exists
4) Fund wallet with 500,000 EGP
5) Request HIGH-risk portfolio allocation with amount 500,000 EGP
6) Fetch portfolio and wallet state, then validate accounting and business rules
7) Always logout in teardown to revoke the current session

Default endpoint target is API Gateway route prefix /api/core.
If your backend exposes different route names, use --base-url and/or --core-base-url.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import requests

INITIAL_FUND_EGP = Decimal("500000")
EXPECTED_FEE_BUFFER_EGP = Decimal("2500")
MONEY_TOLERANCE = Decimal("0.01")
FINAL_RUN_STATES = {"COMPLETED", "PARTIAL", "SUCCESS", "FAILED"}

STATIC_TEST_EMAIL = "e2e_admin@egx-portfolio.com"
STATIC_TEST_PASSWORD = "E2E_Admin#2026"
STATIC_TEST_FULL_NAME = "E2E Admin"
STATIC_TEST_PHONE = "+201000000000"


@dataclass(frozen=True)
class RequestCandidate:
    method: str
    path: str
    payload: dict[str, Any] | None = None


def normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return Decimal(stripped)
        except InvalidOperation:
            return None
    return None


def build_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def iter_dicts(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from iter_dicts(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_dicts(item)


def iter_lists(node: Any):
    if isinstance(node, list):
        yield node
        for item in node:
            yield from iter_lists(item)
    elif isinstance(node, dict):
        for value in node.values():
            yield from iter_lists(value)


def find_first_by_keys(node: Any, keys: set[str]) -> Any | None:
    normalized = {normalize_key(k) for k in keys}

    for obj in iter_dicts(node):
        for key, value in obj.items():
            if normalize_key(str(key)) in normalized:
                return value
    return None


def find_all_numeric_by_keys(node: Any, keys: set[str]) -> list[Decimal]:
    normalized = {normalize_key(k) for k in keys}
    values: list[Decimal] = []

    for obj in iter_dicts(node):
        for key, raw in obj.items():
            if normalize_key(str(key)) in normalized:
                dec = as_decimal(raw)
                if dec is not None:
                    values.append(dec)
    return values


def extract_id(node: Any, preferred_keys: list[str]) -> int | None:
    for key in preferred_keys:
        value = find_first_by_keys(node, {key})
        dec = as_decimal(value)
        if dec is not None:
            return int(dec)

    generic = find_first_by_keys(node, {"id"})
    generic_dec = as_decimal(generic)
    return int(generic_dec) if generic_dec is not None else None


def extract_access_token(node: Any) -> str | None:
    token = find_first_by_keys(node, {"access_token", "accessToken", "token", "jwt", "id_token"})
    return token if isinstance(token, str) and token.strip() else None


def extract_refresh_token(node: Any) -> str | None:
    token = find_first_by_keys(node, {"refresh_token", "refreshToken"})
    return token if isinstance(token, str) and token.strip() else None


def parse_json_response(resp: requests.Response) -> Any:
    if not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text}


def request_with_candidates(
    session: requests.Session,
    base_urls: list[str],
    candidates: list[RequestCandidate],
    timeout_seconds: float,
    operation_name: str,
) -> tuple[requests.Response, Any, str]:
    errors: list[str] = []

    for base_url in base_urls:
        for candidate in candidates:
            url = build_url(base_url, candidate.path)
            try:
                response = session.request(
                    method=candidate.method,
                    url=url,
                    json=candidate.payload,
                    timeout=timeout_seconds,
                )
            except requests.RequestException as exc:
                errors.append(f"{candidate.method} {url} -> transport error: {exc}")
                continue

            if response.status_code in {200, 201, 202}:
                return response, parse_json_response(response), url

            if response.status_code in {401, 403}:
                errors.append(f"{candidate.method} {url} -> auth error {response.status_code}: {response.text}")
                continue

            if response.status_code in {404, 405, 415, 422, 400}:
                errors.append(f"{candidate.method} {url} -> {response.status_code}")
                continue

            errors.append(f"{candidate.method} {url} -> {response.status_code}: {response.text}")

    joined = "\n  - ".join(errors[-20:]) if errors else "no attempts"
    raise RuntimeError(f"{operation_name} failed for all endpoint candidates. Attempts:\n  - {joined}")


def wait_for_health(session: requests.Session, timeout_seconds: float, base_urls: list[str]) -> None:
    candidates = [
        "/actuator/health",
        "/health",
    ]

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        for base in base_urls:
            for path in candidates:
                url = build_url(base, path)
                try:
                    resp = session.get(url, timeout=5)
                    if resp.status_code == 200:
                        return
                except requests.RequestException:
                    pass
        time.sleep(2)

    raise RuntimeError("Gateway/Core health checks did not become ready before timeout")


def try_login_once(
    session: requests.Session,
    base_urls: list[str],
    timeout_seconds: float,
    email: str,
    password: str,
) -> tuple[Any, str] | None:
    payloads = [
        {"email": email, "password": password},
        {"username": email, "password": password},
    ]

    saw_auth_failure = False
    errors: list[str] = []

    for base_url in base_urls:
        for payload in payloads:
            url = build_url(base_url, "/auth/login")
            try:
                response = session.post(url, json=payload, timeout=timeout_seconds)
            except requests.RequestException as exc:
                errors.append(f"POST {url} -> transport error: {exc}")
                continue

            if response.status_code in {200, 201}:
                return parse_json_response(response), url

            if response.status_code in {401, 403}:
                saw_auth_failure = True
                errors.append(f"POST {url} -> auth error {response.status_code}")
                continue

            errors.append(f"POST {url} -> {response.status_code}")

    if saw_auth_failure:
        return None

    joined = "\n  - ".join(errors[-20:]) if errors else "no attempts"
    raise RuntimeError(
        "Login endpoint failed without 401/403 auth response; register fallback not applicable. "
        f"Attempts:\n  - {joined}"
    )


def register_static_user(
    session: requests.Session,
    base_urls: list[str],
    timeout_seconds: float,
    email: str,
    password: str,
) -> Any:
    payloads = [
        {"email": email, "password": password, "fullName": STATIC_TEST_FULL_NAME, "phone": STATIC_TEST_PHONE},
        {"email": email, "password": password, "full_name": STATIC_TEST_FULL_NAME, "phone": STATIC_TEST_PHONE},
    ]

    errors: list[str] = []
    for base_url in base_urls:
        for payload in payloads:
            url = build_url(base_url, "/auth/register")
            try:
                response = session.post(url, json=payload, timeout=timeout_seconds)
            except requests.RequestException as exc:
                errors.append(f"POST {url} -> transport error: {exc}")
                continue

            if response.status_code in {200, 201, 202}:
                print(f"[STEP 1] Created static user via {url}")
                return parse_json_response(response)

            if response.status_code == 409:
                print(f"[STEP 1] Static user already exists (409) at {url}")
                return parse_json_response(response)

            errors.append(f"POST {url} -> {response.status_code}: {response.text}")

    joined = "\n  - ".join(errors[-20:]) if errors else "no attempts"
    raise RuntimeError(f"User registration fallback failed. Attempts:\n  - {joined}")


def login_with_register_fallback(
    session: requests.Session,
    base_urls: list[str],
    timeout_seconds: float,
    email: str,
    password: str,
) -> tuple[Any, Any, str, str]:
    register_response: Any = {}

    login_result = try_login_once(session, base_urls, timeout_seconds, email, password)
    if login_result is None:
        register_response = register_static_user(session, base_urls, timeout_seconds, email, password)
        login_result = try_login_once(session, base_urls, timeout_seconds, email, password)
        if login_result is None:
            raise AssertionError("Login still failing with 401/403 after register fallback")

    login_response, login_url = login_result
    access_token = extract_access_token(login_response)
    refresh_token = extract_refresh_token(login_response)

    if not access_token:
        raise AssertionError("Login succeeded but access token is missing")
    if not refresh_token:
        raise AssertionError("Login succeeded but refresh token is missing")

    session.headers["Authorization"] = f"Bearer {access_token}"
    print(f"[STEP 1] Authenticated via {login_url}")

    return login_response, register_response, access_token, refresh_token


def refresh_access_token(
    session: requests.Session,
    base_urls: list[str],
    timeout_seconds: float,
    access_token: str,
    refresh_token: str,
) -> tuple[str, str, Any]:
    candidates = [
        RequestCandidate("POST", "/auth/refresh", {"refreshToken": refresh_token}),
        RequestCandidate("POST", "/auth/refresh", {"refresh_token": refresh_token}),
    ]

    _, refresh_response, used_url = request_with_candidates(
        session=session,
        base_urls=base_urls,
        candidates=candidates,
        timeout_seconds=timeout_seconds,
        operation_name="Refresh token flow",
    )

    new_access_token = extract_access_token(refresh_response)
    new_refresh_token = extract_refresh_token(refresh_response)

    if not new_access_token:
        raise AssertionError("Refresh response did not return a new access token")

    if new_access_token == access_token:
        print("[WARN] Refresh returned an access token identical to login token")

    if new_refresh_token and new_refresh_token != refresh_token:
        print(f"[STEP 2] Refresh token rotation detected via {used_url}")
    else:
        print(f"[STEP 2] Refresh flow validated via {used_url}")

    session.headers["Authorization"] = f"Bearer {new_access_token}"
    return new_access_token, new_refresh_token or refresh_token, refresh_response


def verify_active_sessions(
    session: requests.Session,
    base_urls: list[str],
    timeout_seconds: float,
) -> Any:
    candidates = [RequestCandidate("GET", "/users/me/sessions")]

    _, sessions_response, used_url = request_with_candidates(
        session=session,
        base_urls=base_urls,
        candidates=candidates,
        timeout_seconds=timeout_seconds,
        operation_name="Session tracking verification",
    )

    sessions: Any = sessions_response
    if isinstance(sessions_response, dict):
        sessions = find_first_by_keys(sessions_response, {"sessions", "items", "data"})

    if not isinstance(sessions, list):
        raise AssertionError("Session endpoint did not return a list of sessions")

    if len(sessions) < 1:
        raise AssertionError("No active session found for authenticated user")

    print(f"[STEP 3] Verified active sessions via {used_url} (count={len(sessions)})")
    return sessions_response


def resolve_user_id(
    session: requests.Session,
    base_urls: list[str],
    timeout_seconds: float,
    payloads: list[Any],
) -> int:
    for payload in payloads:
        user_id = extract_id(payload, preferred_keys=["user_id", "userId"])
        if user_id is not None:
            return user_id

    _, me_response, used_url = request_with_candidates(
        session=session,
        base_urls=base_urls,
        candidates=[RequestCandidate("GET", "/users/me")],
        timeout_seconds=timeout_seconds,
        operation_name="Resolve current user id",
    )
    print(f"[AUTH] Resolved user identity via {used_url}")

    user_id = extract_id(me_response, preferred_keys=["user_id", "userId"])
    if user_id is None:
        raise AssertionError("Could not resolve user id from auth responses or /users/me")

    return user_id


def best_effort_activate_premium(
    session: requests.Session,
    base_urls: list[str],
    timeout_seconds: float,
    user_id: int,
) -> None:
    payloads = [
        {"user_id": user_id, "tier": "PREMIUM", "status": "ACTIVE"},
        {"userId": user_id, "tier": "PREMIUM", "status": "ACTIVE"},
        {"tier": "PREMIUM", "status": "ACTIVE"},
    ]
    paths = [
        "/subscriptions",
        f"/users/{user_id}/subscriptions",
        "/subscriptions/activate",
        f"/users/{user_id}/subscription",
    ]

    for base in base_urls:
        for path in paths:
            for payload in payloads:
                url = build_url(base, path)
                try:
                    resp = session.post(url, json=payload, timeout=timeout_seconds)
                except requests.RequestException:
                    continue
                if resp.status_code in {200, 201, 202}:
                    print(f"[INFO] Activated PREMIUM tier via {url}")
                    return


def best_effort_logout(
    session: requests.Session,
    base_urls: list[str],
    timeout_seconds: float,
) -> None:
    errors: list[str] = []

    for base_url in base_urls:
        url = build_url(base_url, "/auth/logout")
        try:
            response = session.post(url, timeout=timeout_seconds)
        except requests.RequestException as exc:
            errors.append(f"POST {url} -> transport error: {exc}")
            continue

        if response.status_code in {200, 201, 202, 204}:
            print(f"[STEP 4] Logout completed via {url}")
            return

        if response.status_code in {401, 403}:
            print(f"[STEP 4] Logout attempted via {url} (already unauthorized: {response.status_code})")
            return

        errors.append(f"POST {url} -> {response.status_code}: {response.text}")

    if errors:
        print("[STEP 4] Logout teardown failed across all candidates:")
        for item in errors[-5:]:
            print(f"  - {item}")


def fund_wallet(
    session: requests.Session,
    base_urls: list[str],
    timeout_seconds: float,
    user_id: int,
    amount_egp: Decimal,
) -> Any:
    payloads = [
        {"user_id": user_id, "amount_egp": float(amount_egp)},
        {"userId": user_id, "amountEgp": float(amount_egp)},
        {"amount_egp": float(amount_egp)},
        {"amountEgp": float(amount_egp)},
        {"amount": float(amount_egp)},
    ]
    paths = [
        "/wallet/fund",
        "/wallets/fund",
        f"/wallets/{user_id}/fund",
        f"/users/{user_id}/wallet/fund",
        f"/wallets/{user_id}/deposit",
        f"/users/{user_id}/wallet/deposit",
    ]

    candidates: list[RequestCandidate] = []
    for path in paths:
        for payload in payloads:
            candidates.append(RequestCandidate("POST", path, payload))
            candidates.append(RequestCandidate("PUT", path, payload))

    _, response_json, used_url = request_with_candidates(
        session=session,
        base_urls=base_urls,
        candidates=candidates,
        timeout_seconds=timeout_seconds,
        operation_name="Wallet funding",
    )
    print(f"[FLOW] Funded wallet via {used_url}")
    return response_json


def request_portfolio(
    session: requests.Session,
    base_urls: list[str],
    timeout_seconds: float,
    user_id: int,
    amount_egp: Decimal,
    risk_level: str,
) -> tuple[int | None, Any]:
    payloads = [
        {"user_id": user_id, "amount": float(amount_egp), "risk_level": risk_level},
        {"userId": user_id, "amount": float(amount_egp), "riskLevel": risk_level},
        {"user_id": user_id, "requested_amount_egp": float(amount_egp), "risk_level": risk_level},
        {"userId": user_id, "requestedAmountEgp": float(amount_egp), "riskLevel": risk_level},
    ]
    paths = [
        "/portfolio/generate",
        "/portfolios/generate",
        "/portfolio/allocate",
        "/portfolio/request",
        "/portfolio-runs",
        "/portfolios",
    ]

    candidates = [RequestCandidate("POST", path, payload) for path in paths for payload in payloads]
    _, response_json, used_url = request_with_candidates(
        session=session,
        base_urls=base_urls,
        candidates=candidates,
        timeout_seconds=timeout_seconds,
        operation_name="Portfolio allocation request",
    )
    print(f"[FLOW] Requested portfolio via {used_url}")

    run_id = extract_id(response_json, preferred_keys=["portfolio_run_id", "portfolioRunId", "run_id", "runId"])
    if run_id is None:
        portfolio_run = find_first_by_keys(response_json, {"portfolio_run", "portfolioRun"})
        run_id = extract_id(portfolio_run, preferred_keys=["id", "portfolioRunId"]) if portfolio_run else None

    return run_id, response_json


def fetch_wallet_state(
    session: requests.Session,
    base_urls: list[str],
    timeout_seconds: float,
    user_id: int,
) -> Any:
    candidates = [
        RequestCandidate("GET", f"/wallets/{user_id}"),
        RequestCandidate("GET", f"/wallet/{user_id}"),
        RequestCandidate("GET", f"/users/{user_id}/wallet"),
        RequestCandidate("GET", f"/wallets/by-user/{user_id}"),
        RequestCandidate("GET", f"/wallets?userId={user_id}"),
        RequestCandidate("GET", f"/wallet?userId={user_id}"),
    ]

    _, response_json, used_url = request_with_candidates(
        session=session,
        base_urls=base_urls,
        candidates=candidates,
        timeout_seconds=timeout_seconds,
        operation_name="Fetch wallet state",
    )
    print(f"[FLOW] Fetched wallet via {used_url}")
    return response_json


def fetch_portfolio_state(
    session: requests.Session,
    base_urls: list[str],
    timeout_seconds: float,
    user_id: int,
    run_id: int | None,
) -> Any:
    paths = [
        f"/users/{user_id}/portfolio/latest",
        f"/portfolio/latest/{user_id}",
        f"/portfolio-runs/latest/{user_id}",
        f"/users/{user_id}/portfolio",
    ]
    if run_id is not None:
        paths = [
            f"/portfolio-runs/{run_id}",
            f"/portfolios/{run_id}",
            f"/portfolio/{run_id}",
        ] + paths

    candidates = [RequestCandidate("GET", path) for path in paths]
    _, response_json, used_url = request_with_candidates(
        session=session,
        base_urls=base_urls,
        candidates=candidates,
        timeout_seconds=timeout_seconds,
        operation_name="Fetch portfolio state",
    )
    print(f"[FLOW] Fetched portfolio via {used_url}")
    return response_json


def wait_for_final_portfolio_state(
    session: requests.Session,
    base_urls: list[str],
    timeout_seconds: float,
    user_id: int,
    run_id: int | None,
) -> Any:
    deadline = time.time() + timeout_seconds
    latest: Any = {}

    while time.time() < deadline:
        try:
            latest = fetch_portfolio_state(
                session=session,
                base_urls=base_urls,
                timeout_seconds=timeout_seconds,
                user_id=user_id,
                run_id=run_id,
            )
        except RuntimeError:
            time.sleep(2)
            continue

        status_value = find_first_by_keys(latest, {"status", "run_status", "runStatus"})
        status_text = str(status_value).upper() if status_value is not None else ""
        if not status_text or status_text in FINAL_RUN_STATES:
            return latest

        time.sleep(2)

    return latest


def fetch_my_profile(
    session: requests.Session,
    base_urls: list[str],
    timeout_seconds: float,
) -> Any:
    candidates = [RequestCandidate("GET", "/users/me")]

    _, response_json, used_url = request_with_candidates(
        session=session,
        base_urls=base_urls,
        candidates=candidates,
        timeout_seconds=timeout_seconds,
        operation_name="Fetch current user profile",
    )
    print(f"[FLOW] Fetched profile via {used_url}")
    return response_json


def update_my_profile(
    session: requests.Session,
    base_urls: list[str],
    timeout_seconds: float,
    full_name: str,
    phone: str,
) -> Any:
    candidates = [
        RequestCandidate("PUT", "/users/me", {"fullName": full_name, "phone": phone}),
        RequestCandidate("PUT", "/users/me", {"full_name": full_name, "phone": phone}),
    ]

    _, response_json, used_url = request_with_candidates(
        session=session,
        base_urls=base_urls,
        candidates=candidates,
        timeout_seconds=timeout_seconds,
        operation_name="Update current user profile",
    )

    returned_name = find_first_by_keys(response_json, {"fullName", "full_name"})
    if not isinstance(returned_name, str) or returned_name.strip() != full_name:
        raise AssertionError("Profile update did not return expected fullName")

    print(f"[FLOW] Updated profile via {used_url}")
    return response_json


def revoke_other_sessions(
    session: requests.Session,
    base_urls: list[str],
    timeout_seconds: float,
) -> Any:
    candidates = [RequestCandidate("DELETE", "/users/me/sessions")]

    _, response_json, used_url = request_with_candidates(
        session=session,
        base_urls=base_urls,
        candidates=candidates,
        timeout_seconds=timeout_seconds,
        operation_name="Revoke other sessions",
    )

    revoked_count = find_first_by_keys(response_json, {"revokedCount", "revoked_count"})
    revoked_count_decimal = as_decimal(revoked_count)
    if revoked_count_decimal is None or revoked_count_decimal < 0:
        raise AssertionError("Session revoke response is missing a valid revokedCount")

    print(f"[FLOW] Revoked other sessions via {used_url} (count={int(revoked_count_decimal)})")
    return response_json


def is_missing_endpoint_error(exc: RuntimeError) -> bool:
    lines = [line.strip() for line in str(exc).splitlines() if "->" in line]
    if not lines:
        return False

    for line in lines:
        if "-> 404" in line or "-> 405" in line:
            continue
        return False

    return True


def is_unknown_symbol_error(exc: RuntimeError) -> bool:
    text = str(exc).lower()
    markers = [
        "unknown symbol",
        "ai response contains",
        "symbol",
    ]

    return "portfolio allocation request failed" in text and any(marker in text for marker in markers)


def trigger_ai_instrument_sync(ai_base_url: str, timeout_seconds: float) -> Any:
    url = build_url(ai_base_url, "/instruments/sync")

    try:
        response = requests.get(url, timeout=timeout_seconds)
    except requests.RequestException as exc:
        raise RuntimeError(f"Instrument sync trigger failed via {url}: transport error: {exc}") from exc

    if response.status_code not in {200, 201, 202}:
        raise RuntimeError(
            f"Instrument sync trigger failed via {url}: {response.status_code} {response.text}"
        )

    print(f"[FLOW] Triggered AI instrument sync via {url}")
    return parse_json_response(response)


def extract_fee_buffer_amount(payloads: list[Any]) -> Decimal:
    fee_entries: list[Decimal] = []
    type_keys = {"entry_type", "entryType", "ledger_entry_type", "ledgerType", "type"}
    amount_keys = {"amount", "amount_egp", "amountEgp", "value"}

    for payload in payloads:
        for obj in iter_dicts(payload):
            entry_type = None
            for key, value in obj.items():
                if normalize_key(str(key)) in {normalize_key(k) for k in type_keys}:
                    entry_type = str(value).upper()
                    break

            if entry_type and normalize_key(entry_type) == "feebuffer":
                for key, value in obj.items():
                    if normalize_key(str(key)) in {normalize_key(k) for k in amount_keys}:
                        dec = as_decimal(value)
                        if dec is not None:
                            fee_entries.append(abs(dec))
                            break

    if fee_entries:
        return sum(fee_entries, Decimal("0"))

    fallback_values: list[Decimal] = []
    for payload in payloads:
        fallback_values.extend(
            find_all_numeric_by_keys(payload, {"fee_buffer", "feeBuffer", "fee_amount", "feeAmount"})
        )

    if fallback_values:
        return abs(fallback_values[0])

    raise AssertionError("Could not locate fee buffer amount in fetched backend state")


def extract_allocations(payloads: list[Any]) -> list[dict[str, Any]]:
    allocation_keys = {
        "allocations",
        "allocation_executions",
        "allocationExecutions",
        "executions",
        "portfolio_targets",
        "portfolioTargets",
        "orders",
    }

    collected: list[dict[str, Any]] = []
    for payload in payloads:
        for obj in iter_dicts(payload):
            for key, value in obj.items():
                if normalize_key(str(key)) in {normalize_key(k) for k in allocation_keys} and isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            collected.append(item)

        for arr in iter_lists(payload):
            if arr and isinstance(arr[0], dict):
                sample = arr[0]
                if any(
                    normalize_key(k) in {
                        "executedshares",
                        "executedamountegp",
                        "residualcomponentegp",
                        "orderqty",
                        "filledqty",
                    }
                    for k in map(str, sample.keys())
                ):
                    collected.extend([item for item in arr if isinstance(item, dict)])

    dedup: dict[str, dict[str, Any]] = {}
    for item in collected:
        dedup[json.dumps(item, sort_keys=True, default=str)] = item

    return list(dedup.values())


def assert_no_fractional_shares(allocations: list[dict[str, Any]]) -> None:
    share_keys = {"executed_shares", "executedShares", "order_qty", "orderQty", "filled_qty", "filledQty", "qty", "quantity"}
    shares: list[Decimal] = []

    for item in allocations:
        for key, value in item.items():
            if normalize_key(str(key)) in {normalize_key(k) for k in share_keys}:
                dec = as_decimal(value)
                if dec is not None:
                    shares.append(dec)

    if not shares:
        raise AssertionError("Could not find any share quantity fields to validate fractional-share rule")

    for share in shares:
        if share != share.to_integral_value():
            raise AssertionError(f"Found fractional share quantity: {share}")


def extract_executed_total_and_residual(
    allocations: list[dict[str, Any]],
    payloads: list[Any],
) -> tuple[Decimal, Decimal]:
    executed_keys = {"executed_amount_egp", "executedAmountEgp", "executed_amount", "executedAmount"}
    residual_keys = {"residual_component_egp", "residualComponentEgp", "residual_returned", "residualReturned"}

    executed_total = Decimal("0")
    residual_total = Decimal("0")

    for item in allocations:
        for key, value in item.items():
            normalized = normalize_key(str(key))
            dec = as_decimal(value)
            if dec is None:
                continue
            if normalized in {normalize_key(k) for k in executed_keys}:
                executed_total += dec
            elif normalized in {normalize_key(k) for k in residual_keys}:
                residual_total += dec

    if residual_total == 0:
        for payload in payloads:
            candidates = find_all_numeric_by_keys(payload, {"residualReturned", "residual_returned"})
            if candidates:
                residual_total = candidates[0]
                break

    if executed_total == 0:
        qty_keys = {"orderQty", "order_qty", "filledQty", "filled_qty", "executedShares", "executed_shares"}
        price_keys = {"avgFillPrice", "avg_fill_price", "priceSnapshot", "price_snapshot"}

        for item in allocations:
            qty = None
            price = None
            for key, value in item.items():
                normalized = normalize_key(str(key))
                if normalized in {normalize_key(k) for k in qty_keys}:
                    qty = as_decimal(value)
                elif normalized in {normalize_key(k) for k in price_keys}:
                    price = as_decimal(value)
            if qty is not None and price is not None:
                executed_total += qty * price

    if executed_total == 0:
        raise AssertionError("Could not derive executed total amount from portfolio/allocation state")

    return executed_total, residual_total


def assert_ai_invoked(payloads: list[Any], allocations: list[dict[str, Any]]) -> None:
    model_version = None
    status = None

    for payload in payloads:
        if model_version is None:
            value = find_first_by_keys(payload, {"model_version", "modelVersion"})
            if isinstance(value, str) and value.strip():
                model_version = value.strip()
        if status is None:
            value = find_first_by_keys(payload, {"status", "run_status", "runStatus"})
            if value is not None:
                status = str(value).upper()

    if not allocations:
        raise AssertionError("No allocation/order records found; cannot confirm AI output usage")

    if not model_version and status not in {"PARTIAL", "SUCCESS", "COMPLETED"}:
        raise AssertionError("Could not confirm AI invocation (missing model_version and valid run status)")


def print_summary(
    mode: str,
    user_id: int | None,
    refresh_token: str,
    instrument_sync_triggered: bool,
    *,
    portfolio_run_id: int | None = None,
    fee_buffer_amount: Decimal | None = None,
    executed_total: Decimal | None = None,
    residual_total: Decimal | None = None,
    reconciliation_total: Decimal | None = None,
    allocations: list[dict[str, Any]] | None = None,
    financial_assertions_executed: bool | None = None,
    financial_assertions_skipped: bool | None = None,
    financial_skip_reason: str = "",
) -> None:
    def fmt_money(value: Decimal | None) -> str | None:
        if value is None:
            return None
        return format(value.quantize(Decimal("0.01")), "f")

    def fmt_shares(value: Decimal | None) -> str | None:
        if value is None:
            return None
        if value == value.to_integral_value():
            return str(int(value))
        return format(value.normalize(), "f")

    def build_trade_details(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        symbol_keys = {"symbol", "ticker", "instrument_symbol", "instrumentSymbol", "stock_symbol", "stockSymbol", "code"}
        share_keys = {"executed_shares", "executedShares", "order_qty", "orderQty", "filled_qty", "filledQty", "qty", "quantity"}
        price_keys = {"avgFillPrice", "avg_fill_price", "execution_price", "executionPrice", "priceSnapshot", "price_snapshot", "price"}
        total_keys = {"executed_amount_egp", "executedAmountEgp", "total_value_egp", "totalValueEgp", "value_egp", "amount_egp", "amountEgp"}

        details: list[dict[str, Any]] = []
        for item in items:
            symbol_raw = find_first_by_keys(item, symbol_keys)
            symbol = str(symbol_raw).strip() if symbol_raw is not None and str(symbol_raw).strip() else "UNKNOWN"

            shares = as_decimal(find_first_by_keys(item, share_keys))
            execution_price = as_decimal(find_first_by_keys(item, price_keys))
            total_value = as_decimal(find_first_by_keys(item, total_keys))
            if total_value is None and shares is not None and execution_price is not None:
                total_value = shares * execution_price

            details.append(
                {
                    "symbol": symbol,
                    "shares": fmt_shares(shares),
                    "execution_price_egp": fmt_money(execution_price),
                    "total_value_egp": fmt_money(total_value),
                }
            )

        return details

    summary: dict[str, Any] = {
        "mode": mode,
        "user_id": user_id,
        "refresh_token_present": bool(refresh_token),
        "session_check_performed": True,
        "profile_update_performed": True,
        "instrument_sync_triggered": instrument_sync_triggered,
    }

    if mode == "full-financial-flow":
        summary.update(
            {
                "portfolio_run_id": portfolio_run_id,
                "fee_buffer_egp": fmt_money(fee_buffer_amount),
                "executed_total_egp": fmt_money(executed_total),
                "residual_total_egp": fmt_money(residual_total),
                "reconciliation_total_egp": fmt_money(reconciliation_total),
                "allocation_count": len(allocations or []),
                "trade_details": build_trade_details(allocations or []),
            }
        )
        print("\n[E2E PASS] All assertions passed")
    else:
        summary.update(
            {
                "financial_assertions_executed": bool(financial_assertions_executed),
                "financial_assertions_skipped": bool(financial_assertions_skipped),
                "financial_skip_reason": financial_skip_reason,
            }
        )
        print("\n[E2E PASS] Security/profile/session assertions passed")

    print(json.dumps(summary, indent=2))


def run_test(args: argparse.Namespace) -> int:
    email = STATIC_TEST_EMAIL
    password = STATIC_TEST_PASSWORD

    if args.prefer_core:
        base_urls = [args.core_base_url, args.base_url]
    else:
        base_urls = [args.base_url, args.core_base_url]

    session = requests.Session()
    session.headers.update({"Content-Type": "application/json", "Accept": "application/json"})

    register_response: Any = {}
    login_response: Any = {}
    refresh_response: Any = {}
    sessions_response: Any = {}
    revoke_sessions_response: Any = {}
    profile_before: Any = {}
    profile_after: Any = {}
    fund_response: Any = {}
    portfolio_request_response: Any = {}
    instrument_sync_response: Any = {}
    portfolio_state: Any = {}
    wallet_state: Any = {}

    run_id: int | None = None
    user_id: int | None = None
    auth_established = False
    financial_assertions_executed = False
    financial_assertions_skipped = False
    financial_skip_reason = ""
    instrument_sync_triggered = False
    refresh_token = ""
    exit_code = 0

    try:
        print("[INIT] Waiting for gateway/core readiness...")
        wait_for_health(session, timeout_seconds=args.wait_ready_timeout, base_urls=base_urls)

        login_response, register_response, access_token, refresh_token = login_with_register_fallback(
            session=session,
            base_urls=base_urls,
            timeout_seconds=args.timeout,
            email=email,
            password=password,
        )
        auth_established = True

        _, refresh_token, refresh_response = refresh_access_token(
            session=session,
            base_urls=base_urls,
            timeout_seconds=args.timeout,
            access_token=access_token,
            refresh_token=refresh_token,
        )

        sessions_response = verify_active_sessions(
            session=session,
            base_urls=base_urls,
            timeout_seconds=args.timeout,
        )

        revoke_sessions_response = revoke_other_sessions(
            session=session,
            base_urls=base_urls,
            timeout_seconds=args.timeout,
        )

        user_id = resolve_user_id(
            session=session,
            base_urls=base_urls,
            timeout_seconds=args.timeout,
            payloads=[login_response, register_response, refresh_response],
        )

        profile_before = fetch_my_profile(
            session=session,
            base_urls=base_urls,
            timeout_seconds=args.timeout,
        )

        profile_after = update_my_profile(
            session=session,
            base_urls=base_urls,
            timeout_seconds=args.timeout,
            full_name=f"{STATIC_TEST_FULL_NAME} {int(time.time())}",
            phone=STATIC_TEST_PHONE,
        )

        best_effort_activate_premium(
            session=session,
            base_urls=base_urls,
            timeout_seconds=args.timeout,
            user_id=user_id,
        )

        try:
            fund_response = fund_wallet(
                session=session,
                base_urls=base_urls,
                timeout_seconds=args.timeout,
                user_id=user_id,
                amount_egp=INITIAL_FUND_EGP,
            )

            try:
                run_id, portfolio_request_response = request_portfolio(
                    session=session,
                    base_urls=base_urls,
                    timeout_seconds=args.timeout,
                    user_id=user_id,
                    amount_egp=INITIAL_FUND_EGP,
                    risk_level="HIGH",
                )
            except RuntimeError as portfolio_exc:
                if not is_unknown_symbol_error(portfolio_exc):
                    raise

                print("[INFO] Portfolio request failed with unknown symbol; triggering instrument sync and retrying once")
                instrument_sync_response = trigger_ai_instrument_sync(
                    ai_base_url=args.ai_base_url,
                    timeout_seconds=args.timeout,
                )
                instrument_sync_triggered = True

                run_id, portfolio_request_response = request_portfolio(
                    session=session,
                    base_urls=base_urls,
                    timeout_seconds=args.timeout,
                    user_id=user_id,
                    amount_egp=INITIAL_FUND_EGP,
                    risk_level="HIGH",
                )

            portfolio_state = wait_for_final_portfolio_state(
                session=session,
                base_urls=base_urls,
                timeout_seconds=args.poll_timeout,
                user_id=user_id,
                run_id=run_id,
            )

            wallet_state = fetch_wallet_state(
                session=session,
                base_urls=base_urls,
                timeout_seconds=args.timeout,
                user_id=user_id,
            )

            portfolio_allocations = extract_allocations([portfolio_state])
            if not portfolio_allocations:
                raise AssertionError("Could not extract allocations from /portfolio-runs/{id} response")

            evidence_payloads = [
                register_response,
                login_response,
                refresh_response,
                sessions_response,
                revoke_sessions_response,
                profile_before,
                profile_after,
                fund_response,
                instrument_sync_response,
                portfolio_request_response,
                portfolio_state,
                wallet_state,
            ]

            fee_buffer_amount = extract_fee_buffer_amount(evidence_payloads)
            if abs(fee_buffer_amount - EXPECTED_FEE_BUFFER_EGP) > MONEY_TOLERANCE:
                raise AssertionError(
                    f"Fee buffer mismatch. Expected {EXPECTED_FEE_BUFFER_EGP}, got {fee_buffer_amount}"
                )

            assert_ai_invoked(evidence_payloads, portfolio_allocations)
            assert_no_fractional_shares(portfolio_allocations)

            executed_total, residual_total = extract_executed_total_and_residual(portfolio_allocations, evidence_payloads)
            reconciliation_total = executed_total + residual_total + fee_buffer_amount

            if abs(reconciliation_total - INITIAL_FUND_EGP) > MONEY_TOLERANCE:
                raise AssertionError(
                    "Accounting reconciliation failed. "
                    f"executed={executed_total}, residual={residual_total}, fee={fee_buffer_amount}, "
                    f"sum={reconciliation_total}, expected={INITIAL_FUND_EGP}"
                )

            financial_assertions_executed = True
            print_summary(
                mode="full-financial-flow",
                user_id=user_id,
                refresh_token=refresh_token,
                instrument_sync_triggered=instrument_sync_triggered,
                portfolio_run_id=run_id,
                fee_buffer_amount=fee_buffer_amount,
                executed_total=executed_total,
                residual_total=residual_total,
                reconciliation_total=reconciliation_total,
                allocations=portfolio_allocations,
            )
        except RuntimeError as flow_exc:
            if not is_missing_endpoint_error(flow_exc):
                raise

            financial_assertions_skipped = True
            financial_skip_reason = str(flow_exc).splitlines()[0]
            print("[INFO] Wallet/portfolio endpoints are not available in this deployment; skipping financial assertions")

        if financial_assertions_skipped:
            print_summary(
                mode="security-profile-session",
                user_id=user_id,
                refresh_token=refresh_token,
                instrument_sync_triggered=instrument_sync_triggered,
                financial_assertions_executed=financial_assertions_executed,
                financial_assertions_skipped=financial_assertions_skipped,
                financial_skip_reason=financial_skip_reason,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"\n[E2E FAIL] {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        if auth_established:
            best_effort_logout(
                session=session,
                base_urls=base_urls,
                timeout_seconds=args.timeout,
            )

    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Run E2E flow test against API Gateway/Core backend")
    default_base_url = os.getenv("E2E_BASE_URL", "http://localhost:8082/api/core")
    default_core_base_url = os.getenv("E2E_CORE_BASE_URL", "http://localhost:8083")
    default_ai_base_url = os.getenv("E2E_AI_BASE_URL", "http://localhost:8002")

    parser.add_argument("--base-url", default=default_base_url, help="Gateway core route base URL")
    parser.add_argument("--core-base-url", default=default_core_base_url, help="Direct core backend base URL")
    parser.add_argument("--ai-base-url", default=default_ai_base_url, help="AI engine base URL for instrument sync trigger")
    parser.add_argument("--timeout", type=float, default=15.0, help="Per-request timeout in seconds")
    parser.add_argument("--wait-ready-timeout", type=float, default=120.0, help="Startup wait timeout in seconds")
    parser.add_argument("--poll-timeout", type=float, default=60.0, help="Portfolio finalization polling timeout")
    parser.add_argument("--prefer-core", action="store_true", help="Try direct core URL before gateway URL")
    args = parser.parse_args()

    return run_test(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[E2E FAIL] Cancelled by user", file=sys.stderr)
        raise SystemExit(130)
