from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from .data_pipeline import MarketDataset

RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]


@dataclass(frozen=True)
class RejectedSymbolInfo:
    symbol: str
    reason: str


@dataclass(frozen=True)
class ConstraintOutput:
    symbols: list[str]
    expected_returns: np.ndarray
    covariance: np.ndarray
    sectors: dict[str, str]
    bounds: list[tuple[float, float]]
    sector_to_indices: dict[str, list[int]]
    liquidity_caps_egp: dict[str, float]
    rejected_symbols: list[RejectedSymbolInfo]
    warnings: list[str]


def build_constraint_output(
    dataset: MarketDataset,
    budget_egp: float,
    risk_level: RiskLevel,
    max_sector_weight: float,
    exclude_suspended: bool,
) -> ConstraintOutput:
    if budget_egp <= 0:
        raise ValueError("budget_egp must be greater than zero")

    warnings: list[str] = []
    rejected: list[RejectedSymbolInfo] = []

    max_sector_weight = float(max(0.0, min(1.0, max_sector_weight)))
    if max_sector_weight <= 0:
        max_sector_weight = 0.40
        warnings.append("Invalid max_sector_weight; defaulted to 0.40")

    eligible_symbols: list[str] = []
    for symbol in sorted(dataset.snapshots.keys()):
        snapshot = dataset.snapshots[symbol]

        if exclude_suspended and symbol in dataset.suspended_symbols:
            rejected.append(RejectedSymbolInfo(symbol=symbol, reason="SUSPENDED"))
            continue

        liquidity_weight_cap = snapshot.liquidity_cap_value_egp / budget_egp
        if liquidity_weight_cap <= 0.0:
            rejected.append(RejectedSymbolInfo(symbol=symbol, reason="LIQUIDITY_CAP"))
            continue

        eligible_symbols.append(symbol)

    if risk_level == "LOW":
        low_risk_symbols = _select_low_risk_subset(dataset=dataset, symbols=eligible_symbols)
        low_risk_set = set(low_risk_symbols)

        for symbol in eligible_symbols:
            if symbol not in low_risk_set:
                rejected.append(RejectedSymbolInfo(symbol=symbol, reason="RISK_FILTER_LOW"))

        eligible_symbols = low_risk_symbols

    if not eligible_symbols:
        return _empty_output(rejected=rejected, warnings=warnings)

    sectors = {symbol: dataset.sector_map.get(symbol, "UNCLASSIFIED") for symbol in eligible_symbols}
    sector_to_indices = _build_sector_index_map(eligible_symbols, sectors)

    # Use annualized estimates for MPT objective.
    returns_frame = dataset.returns[eligible_symbols].dropna(how="all").fillna(0.0)
    if returns_frame.shape[0] < 30:
        warnings.append("Limited return history available; optimization stability may be reduced")

    expected_returns = (returns_frame.mean() * 252.0).to_numpy(dtype=float)
    covariance = (returns_frame.cov() * 252.0).to_numpy(dtype=float)
    covariance = covariance + np.eye(covariance.shape[0], dtype=float) * 1e-6

    kept_symbols, bounds, liquidity_caps_egp, low_liquidity_rejected = _build_symbol_bounds(
        symbols=eligible_symbols,
        dataset=dataset,
        budget_egp=budget_egp,
        risk_level=risk_level,
    )
    rejected.extend(low_liquidity_rejected)

    if not kept_symbols:
        warnings.append("No symbols satisfy liquidity requirements for requested budget")
        return _empty_output(rejected=rejected, warnings=warnings)

    # Align arrays/maps after any symbol dropped by tight liquidity checks.
    if len(kept_symbols) != len(eligible_symbols):
        filtered_indices = [eligible_symbols.index(symbol) for symbol in kept_symbols]
        expected_returns = expected_returns[filtered_indices]
        covariance = covariance[np.ix_(filtered_indices, filtered_indices)]
        sectors = {symbol: sectors[symbol] for symbol in kept_symbols}
        sector_to_indices = _build_sector_index_map(kept_symbols, sectors)
        eligible_symbols = kept_symbols

    total_upper = float(sum(upper for _, upper in bounds))
    if total_upper < 1.0 - 1e-8:
        warnings.append("Aggregate liquidity caps are too tight for full deployment of budget")
        rejected.extend(
            RejectedSymbolInfo(symbol=symbol, reason="LIQUIDITY_BUDGET_INFEASIBLE")
            for symbol in eligible_symbols
        )
        return _empty_output(rejected=rejected, warnings=warnings)

    _ = max_sector_weight  # Enforced in optimizer.

    return ConstraintOutput(
        symbols=eligible_symbols,
        expected_returns=expected_returns,
        covariance=covariance,
        sectors=sectors,
        bounds=bounds,
        sector_to_indices=sector_to_indices,
        liquidity_caps_egp=liquidity_caps_egp,
        rejected_symbols=rejected,
        warnings=warnings,
    )


def _empty_output(rejected: list[RejectedSymbolInfo], warnings: list[str]) -> ConstraintOutput:
    return ConstraintOutput(
        symbols=[],
        expected_returns=np.array([], dtype=float),
        covariance=np.array([], dtype=float),
        sectors={},
        bounds=[],
        sector_to_indices={},
        liquidity_caps_egp={},
        rejected_symbols=rejected,
        warnings=warnings,
    )


def _select_low_risk_subset(dataset: MarketDataset, symbols: list[str]) -> list[str]:
    if len(symbols) <= 10:
        return symbols

    frame = pd.DataFrame(
        {
            "symbol": symbols,
            "volatility": [dataset.snapshots[s].volatility_20d for s in symbols],
            "market_cap_rank": [dataset.market_cap_rank.get(s, 30) for s in symbols],
        }
    )

    frame["vol_rank"] = frame["volatility"].rank(method="dense", ascending=True)
    frame["score"] = frame["market_cap_rank"] * 0.60 + frame["vol_rank"] * 0.40
    ranked = frame.sort_values(["score", "market_cap_rank", "volatility"], ascending=[True, True, True])

    return ranked.head(10)["symbol"].tolist()


def _build_sector_index_map(symbols: list[str], sectors: dict[str, str]) -> dict[str, list[int]]:
    mapping: dict[str, list[int]] = {}
    for idx, symbol in enumerate(symbols):
        mapping.setdefault(sectors[symbol], []).append(idx)
    return mapping


def _build_symbol_bounds(
    symbols: list[str],
    dataset: MarketDataset,
    budget_egp: float,
    risk_level: RiskLevel,
) -> tuple[list[str], list[tuple[float, float]], dict[str, float], list[RejectedSymbolInfo]]:
    risk_cap = {
        "LOW": 0.20,
        "MEDIUM": 0.35,
        "HIGH": 0.50,
    }[risk_level]

    kept_symbols: list[str] = []
    bounds: list[tuple[float, float]] = []
    liquidity_caps_egp: dict[str, float] = {}
    rejected: list[RejectedSymbolInfo] = []

    for symbol in symbols:
        snapshot = dataset.snapshots[symbol]
        liquidity_weight_cap = snapshot.liquidity_cap_value_egp / budget_egp

        upper = min(1.0, risk_cap, max(0.0, float(liquidity_weight_cap)))
        if upper < 0.005:
            rejected.append(RejectedSymbolInfo(symbol=symbol, reason="LIQUIDITY_CAP"))
            continue

        kept_symbols.append(symbol)
        bounds.append((0.0, upper))
        liquidity_caps_egp[symbol] = float(snapshot.liquidity_cap_value_egp)

    return kept_symbols, bounds, liquidity_caps_egp, rejected
