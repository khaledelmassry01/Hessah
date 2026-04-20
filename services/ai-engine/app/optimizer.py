from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize


@dataclass(frozen=True)
class OptimizationResult:
    weights: dict[str, float]
    expected_return: float
    expected_volatility: float
    used_fallback: bool
    warnings: list[str]


def optimize_max_sharpe(
    symbols: list[str],
    expected_returns: np.ndarray,
    covariance: np.ndarray,
    bounds: list[tuple[float, float]],
    sector_to_indices: dict[str, list[int]],
    max_sector_weight: float,
    risk_free_rate: float = 0.25,
    covariance_shrinkage: float = 0.0,
) -> OptimizationResult:
    if not symbols:
        return OptimizationResult(
            weights={},
            expected_return=0.0,
            expected_volatility=0.0,
            used_fallback=True,
            warnings=["No symbols available for optimization"],
        )

    max_sector_weight = float(max(0.0, min(1.0, max_sector_weight)))
    covariance_shrinkage = float(max(0.0, min(1.0, covariance_shrinkage)))
    covariance_used = _shrink_covariance_matrix(covariance, covariance_shrinkage)

    def negative_sharpe(weights: np.ndarray) -> float:
        portfolio_return = float(np.dot(weights, expected_returns))
        variance = float(np.dot(weights, covariance_used @ weights))
        portfolio_vol = max(np.sqrt(max(variance, 0.0)), 1e-9)
        sharpe = (portfolio_return - risk_free_rate) / portfolio_vol
        return -sharpe

    constraints: list[dict] = [
        {
            "type": "eq",
            "fun": lambda w: float(np.sum(w) - 1.0),
        }
    ]

    for indices in sector_to_indices.values():
        constraints.append(
            {
                "type": "ineq",
                "fun": lambda w, idx=indices: float(max_sector_weight - np.sum(w[idx])),
            }
        )

    x0 = _build_initial_guess(bounds)

    result = minimize(
        negative_sharpe,
        x0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 600, "ftol": 1e-9, "disp": False},
    )

    warnings: list[str] = []
    used_fallback = False

    if not result.success or result.x is None:
        used_fallback = True
        warnings.append(f"Primary optimization failed: {result.message}")
        weights = _fallback_feasible_weights(expected_returns, bounds)
    else:
        weights = np.asarray(result.x, dtype=float)

    weights = _repair_weights(weights, bounds)
    weights = _enforce_sector_caps(weights, sector_to_indices, max_sector_weight)
    weights = _repair_weights(weights, bounds)

    portfolio_return = float(np.dot(weights, expected_returns))
    variance = float(np.dot(weights, covariance_used @ weights))
    portfolio_volatility = float(np.sqrt(max(variance, 0.0)))

    normalized = _normalize_for_response(symbols, weights)

    return OptimizationResult(
        weights=normalized,
        expected_return=portfolio_return,
        expected_volatility=portfolio_volatility,
        used_fallback=used_fallback,
        warnings=warnings,
    )


def _shrink_covariance_matrix(covariance: np.ndarray, shrinkage: float) -> np.ndarray:
    if shrinkage <= 0:
        return covariance

    diagonal = np.diag(np.diag(covariance))
    return ((1.0 - shrinkage) * covariance) + (shrinkage * diagonal)


def _build_initial_guess(bounds: list[tuple[float, float]]) -> np.ndarray:
    n_assets = len(bounds)
    raw = np.array([min(1.0 / max(n_assets, 1), upper) for _, upper in bounds], dtype=float)

    if raw.sum() <= 0:
        raw = np.array([upper for _, upper in bounds], dtype=float)

    if raw.sum() <= 0:
        raw = np.ones(n_assets, dtype=float)

    raw /= raw.sum()
    return raw


def _fallback_feasible_weights(expected_returns: np.ndarray, bounds: list[tuple[float, float]]) -> np.ndarray:
    scores = np.maximum(expected_returns, 0.0) + 1e-6
    if float(scores.sum()) <= 0:
        scores = np.ones_like(scores)

    weights = scores / scores.sum()
    return _repair_weights(weights, bounds)


def _repair_weights(weights: np.ndarray, bounds: list[tuple[float, float]]) -> np.ndarray:
    lower = np.array([b[0] for b in bounds], dtype=float)
    upper = np.array([b[1] for b in bounds], dtype=float)

    fixed = np.clip(np.asarray(weights, dtype=float), lower, upper)
    total = float(fixed.sum())

    if total <= 0:
        fixed = upper.copy()
        total = float(fixed.sum())

    if total <= 0:
        fixed = np.ones_like(fixed)
        total = float(fixed.sum())

    fixed /= total

    for _ in range(8):
        fixed = np.clip(fixed, lower, upper)
        total = float(fixed.sum())
        delta = 1.0 - total
        if abs(delta) < 1e-10:
            break

        if delta > 0:
            slack = upper - fixed
            slack_sum = float(slack.sum())
            if slack_sum <= 1e-12:
                break
            fixed += (slack / slack_sum) * delta
        else:
            removable = fixed - lower
            removable_sum = float(removable.sum())
            if removable_sum <= 1e-12:
                break
            fixed += (removable / removable_sum) * delta

    fixed = np.clip(fixed, lower, upper)
    fixed_sum = float(fixed.sum())
    if fixed_sum > 0:
        fixed /= fixed_sum

    return fixed


def _enforce_sector_caps(
    weights: np.ndarray,
    sector_to_indices: dict[str, list[int]],
    max_sector_weight: float,
) -> np.ndarray:
    adjusted = np.asarray(weights, dtype=float).copy()

    for _ in range(5):
        violated = False
        for indices in sector_to_indices.values():
            sector_weight = float(np.sum(adjusted[indices]))
            if sector_weight > max_sector_weight + 1e-9:
                violated = True
                overflow = sector_weight - max_sector_weight
                current = adjusted[indices]
                current_sum = float(current.sum())
                if current_sum > 1e-12:
                    adjusted[indices] -= (current / current_sum) * overflow
                    adjusted[indices] = np.clip(adjusted[indices], 0.0, None)

                non_sector = [idx for idx in range(len(adjusted)) if idx not in indices]
                if non_sector:
                    room = np.maximum(0.0, 1.0 - adjusted[non_sector])
                    room_sum = float(room.sum())
                    if room_sum > 1e-12:
                        adjusted[non_sector] += (room / room_sum) * overflow
        if not violated:
            break

    total = float(adjusted.sum())
    if total > 0:
        adjusted /= total

    return adjusted


def _normalize_for_response(symbols: list[str], weights: np.ndarray) -> dict[str, float]:
    if len(symbols) != len(weights):
        raise ValueError("symbols and weights length mismatch")

    rounded = [round(float(w), 8) for w in weights]
    total = sum(rounded)
    diff = round(1.0 - total, 8)

    if rounded:
        max_idx = int(np.argmax(np.array(rounded, dtype=float)))
        rounded[max_idx] = round(max(0.0, rounded[max_idx] + diff), 8)

    normalized_total = sum(rounded)
    if abs(normalized_total - 1.0) > 1e-6 and normalized_total > 0:
        rounded = [round(value / normalized_total, 8) for value in rounded]

    return {symbol: weight for symbol, weight in zip(symbols, rounded) if weight > 0}
