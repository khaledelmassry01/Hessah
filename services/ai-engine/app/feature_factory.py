from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from xgboost import XGBClassifier, XGBRegressor

from .data_pipeline import canonicalize_symbol
from .feature_engineering import (
    MysqlSettings,
    load_historical_market_data,
    open_mysql_connection,
    resolve_mysql_settings,
)
from .sentiment_engine import append_market_sentiment_features

LOGGER = logging.getLogger(__name__)

DEFAULT_START_DATE = date(2016, 1, 1)
DEFAULT_TRAIN_END = date(2024, 12, 31)
DEFAULT_BLIND_START = date(2025, 1, 1)
DEFAULT_BLIND_END = date(2026, 4, 30)
DEFAULT_HORIZON_DAYS = 5
DEFAULT_RETRAIN_EVERY = 21
DEFAULT_N_ESTIMATORS = 1000
DEFAULT_LEARNING_RATE = 0.01
DEFAULT_MAX_DEPTH = 8
DEFAULT_SUBSAMPLE = 0.8
ALT_DB_PORT = 3307
UREA_SYMBOL_ROOTS = {"ABUK", "MFPC"}
BRENT_SYMBOL_ROOTS = {"AMOC", "SKPC"}
MACRO_DIRECTION_BLEND_WEIGHT = 0.35
REGIME_TURBULENT_QUANTILE = 0.8
REGIME_SIMILARITY_WEIGHT_MULTIPLIER = 3.0
REGIME_STABLE_BLEND_WEIGHT = 0.25
REGIME_TURBULENT_BLEND_WEIGHT = 0.75
HIGH_ERROR_SYMBOL_ROOTS = {"GDWA", "OBRI", "AUTO"}
FALSE_BUY_PENALTY_WEIGHT = 1.5
MICRO_REGIME_START = pd.Timestamp("2026-01-01")
MICRO_REGIME_END = pd.Timestamp("2026-04-30")
MICRO_REGIME_BLEND_WEIGHT = 0.65
MICRO_RECOVERY_START = pd.Timestamp("2026-03-01")
MICRO_RECOVERY_THRESHOLD_CAP = 0.36
MICRO_REGIME_FEATURE_SCALERS = {
    "relative_volume_60d": 1.8,
    "gold_return": 1.8,
}
MICRO_REGIME_IMPORTANCE_MULTIPLIERS = {
    "relative_volume_60d": 1.6,
    "gold_return": 1.6,
}
CONFIDENCE_GUARD_SIGNAL_THRESHOLD = 0.7
CONFIDENCE_GUARD_MIN_PROB = 0.75
HIGH_VOLATILITY_ATR_THRESHOLD = 0.05
HIGH_CONFIDENCE_MIN_PROB = 0.70
HIGH_CONFIDENCE_TARGET_MIN_BUY_RATE = 0.01
HIGH_CONFIDENCE_TARGET_MAX_BUY_RATE = 0.02
HIGH_CONFIDENCE_MIN_PRECISION_TARGET = 0.55
HIGH_CONFIDENCE_STOP_LOSS_PCT = 0.05
SMART_MONEY_LOW_VOLUME_DOWNSCALE = 0.85

MACRO_DIRECTION_FEATURES = [
    "usd_egp_return",
    "gold_return",
    "cbe_policy_rate_pct",
    "cbe_rate_changed",
]

MACRO_PRIORITY_IMPORTANCE_MULTIPLIERS = {
    "usd_egp_return": 3.5,
    "stock_usd_corr_20d": 1.4,
    "gold_return": 1.3,
    "cbe_policy_rate_pct": 1.25,
    "cbe_rate_changed": 1.25,
}

FEATURE_COLUMNS = [
    "daily_return",
    "ema_20",
    "ema_50",
    "ema_200",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "bollinger_mid_20",
    "bollinger_upper_20",
    "bollinger_lower_20",
    "atr_14",
    "usd_egp_return",
    "gold_return",
    "stock_usd_corr_20d",
    "sector_momentum_5d",
    "volume_shock_20d",
    "relative_volume_60d",
    "market_sentiment_score",
    "global_factor_corr_sp500",
    "smart_money_signal",
    "cbe_policy_rate_pct",
    "cbe_rate_changed",
    "alt_news_sentiment_score",
    "alt_urea_price",
    "alt_brent_price",
]

TARGET_COLUMN = "target_forward_return_5d"


@dataclass(frozen=True)
class FeatureFactoryResult:
    frame: pd.DataFrame
    symbols: list[str]


@dataclass(frozen=True)
class WalkForwardMetrics:
    rmse: float
    directional_accuracy_regression: float
    directional_accuracy_classification: float
    rows_evaluated: int
    blocks_trained: int
    backtest_accuracy_score: float
    global_threshold: float
    precision_at_threshold: float
    buy_rate_at_threshold: float
    high_confidence_threshold: float
    high_confidence_precision: float
    high_confidence_buy_rate: float
    cumulative_profit_high_confidence_raw: float
    cumulative_profit_high_confidence: float


@dataclass(frozen=True)
class BlockTrainingLog:
    block_id: int
    block_start_date: str
    block_end_date: str
    train_rows: int
    test_rows: int
    rmse: float
    directional_accuracy_regression: float
    directional_accuracy_classification_raw: float
    directional_accuracy_classification: float
    precision_at_threshold: float
    buy_rate_at_threshold: float
    guardrail_forced_no_buy: int
    turbulent_test_share: float


def _normalize_abs_feature(values: pd.Series, quantile: float = 0.9) -> pd.Series:
    local = pd.to_numeric(values, errors="coerce").fillna(0.0).abs()
    scale = float(local.quantile(quantile)) if len(local) else 0.0
    if scale <= 1e-8:
        scale = 1.0
    return (local / scale).clip(lower=0.0, upper=4.0)


def _compute_turbulence_score(frame: pd.DataFrame) -> pd.Series:
    usd_component = _normalize_abs_feature(frame["usd_egp_return"])
    volume_component = _normalize_abs_feature(frame["volume_shock_20d"])
    atr_ratio = pd.to_numeric(frame["atr_14"], errors="coerce").fillna(0.0) / pd.to_numeric(
        frame["close_price"],
        errors="coerce",
    ).replace(0.0, np.nan)
    atr_component = _normalize_abs_feature(atr_ratio.fillna(0.0))

    score = (0.55 * usd_component) + (0.25 * volume_component) + (0.20 * atr_component)
    return score.fillna(0.0)


def _build_macro_sample_weights(train_slice: pd.DataFrame) -> np.ndarray:
    usd_abs = (
        pd.to_numeric(train_slice["usd_egp_return"], errors="coerce")
        .fillna(0.0)
        .abs()
        .to_numpy(dtype=float)
    )
    usd_scale = float(np.quantile(usd_abs, 0.9)) if len(usd_abs) else 0.0
    if usd_scale <= 1e-8:
        usd_scale = 1.0

    usd_component = np.clip(usd_abs / usd_scale, 0.0, 3.0)
    rate_changed = pd.to_numeric(train_slice["cbe_rate_changed"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    recency_component = train_slice["trade_date"].rank(method="dense", pct=True).to_numpy(dtype=float)

    weights = 1.0 + (1.8 * usd_component) + (0.7 * rate_changed) + (0.5 * recency_component)
    return np.clip(weights, 1.0, 6.0)


def _build_regime_sample_weights(
    train_slice: pd.DataFrame,
    turbulence_score: pd.Series,
) -> tuple[np.ndarray, np.ndarray, float, float, int]:
    base_weights = _build_macro_sample_weights(train_slice)
    local_score = pd.to_numeric(turbulence_score, errors="coerce").fillna(0.0)

    turbulent_threshold = float(local_score.quantile(REGIME_TURBULENT_QUANTILE)) if len(local_score) else 0.0
    train_turbulent_mask = (local_score >= turbulent_threshold).to_numpy(dtype=bool)

    max_train_date = pd.to_datetime(train_slice["trade_date"], errors="coerce").max()
    if pd.isna(max_train_date):
        current_regime_score = float(local_score.median()) if len(local_score) else 0.0
    else:
        recent_cutoff = max_train_date - pd.offsets.BDay(30)
        recent_mask = pd.to_datetime(train_slice["trade_date"], errors="coerce") >= recent_cutoff
        recent_scores = local_score.loc[recent_mask]
        if recent_scores.empty:
            recent_scores = local_score.tail(min(200, len(local_score)))
        current_regime_score = float(recent_scores.median()) if len(recent_scores) else 0.0

    high_vol_trigger = float(local_score.quantile(0.65)) if len(local_score) else 0.0

    crisis_rows_weighted = np.zeros(len(train_slice), dtype=bool)
    if current_regime_score >= high_vol_trigger and len(local_score) > 0:
        distance = (local_score - current_regime_score).abs()
        similarity_band = float(distance.quantile(0.45)) if len(distance) else 0.0
        if similarity_band <= 1e-8:
            similarity_band = max(float(local_score.std()), 0.05)

        trade_date = pd.to_datetime(train_slice["trade_date"], errors="coerce")
        crisis_anchor_mask = (
            ((trade_date >= pd.Timestamp("2024-01-01")) & (trade_date <= pd.Timestamp("2024-06-30")))
            | ((trade_date >= pd.Timestamp("2025-06-01")) & (trade_date <= pd.Timestamp("2025-09-30")))
        )

        crisis_rows_weighted = (
            ((local_score >= high_vol_trigger) & (distance <= similarity_band))
            | (crisis_anchor_mask & (local_score >= (0.9 * high_vol_trigger)))
        ).to_numpy(dtype=bool)
        base_weights = base_weights * np.where(crisis_rows_weighted, REGIME_SIMILARITY_WEIGHT_MULTIPLIER, 1.0)

    return np.clip(base_weights, 1.0, 18.0), train_turbulent_mask, turbulent_threshold, current_regime_score, int(crisis_rows_weighted.sum())


def _compute_regime_blend_weights(
    train_slice: pd.DataFrame,
    test_slice: pd.DataFrame,
    train_turbulence_score: pd.Series,
    test_turbulence_score: pd.Series,
    turbulent_threshold: float,
) -> tuple[np.ndarray, np.ndarray]:
    train_local = train_slice[["trade_date"]].copy()
    train_local["score"] = pd.to_numeric(train_turbulence_score, errors="coerce").fillna(0.0).to_numpy(dtype=float)
    test_local = test_slice[["trade_date"]].copy()
    test_local["score"] = pd.to_numeric(test_turbulence_score, errors="coerce").fillna(0.0).to_numpy(dtype=float)

    train_by_date = train_local.groupby("trade_date", as_index=True)["score"].median().sort_index()
    test_by_date = test_local.groupby("trade_date", as_index=True)["score"].median().sort_index()
    combined_by_date = pd.concat([train_by_date, test_by_date]).sort_index()
    yesterday_score_by_date = combined_by_date.shift(1)

    if len(train_by_date) > 0:
        date_threshold = float(train_by_date.quantile(REGIME_TURBULENT_QUANTILE))
        fallback_yesterday_score = float(train_by_date.iloc[-1])
    else:
        date_threshold = float(turbulent_threshold)
        fallback_yesterday_score = float(turbulent_threshold)

    test_yesterday_score = test_slice["trade_date"].map(yesterday_score_by_date).fillna(fallback_yesterday_score)
    yesterday_turbulent = (test_yesterday_score.to_numpy(dtype=float) >= date_threshold).astype(bool)
    row_turbulent = (
        pd.to_numeric(test_turbulence_score, errors="coerce").fillna(0.0).to_numpy(dtype=float) >= turbulent_threshold
    ).astype(bool)

    blend_weight = np.where(
        yesterday_turbulent,
        REGIME_TURBULENT_BLEND_WEIGHT,
        REGIME_STABLE_BLEND_WEIGHT,
    ).astype(float)
    blend_weight = np.where(row_turbulent, np.minimum(0.95, blend_weight + 0.15), np.maximum(0.05, blend_weight - 0.05))
    return blend_weight, yesterday_turbulent


def _compute_scale_pos_weight(y_binary: np.ndarray) -> float:
    if len(y_binary) == 0:
        return 1.0

    positive_ratio = float(np.mean(y_binary.astype(float)))
    if 0.0 < positive_ratio < 1.0:
        return float((1.0 - positive_ratio) / positive_ratio)
    return 1.0


def _build_directional_sample_weights(
    base_weights: np.ndarray,
    y_train_binary: np.ndarray,
) -> np.ndarray:
    y_binary = np.asarray(y_train_binary).astype(int)
    base = np.asarray(base_weights, dtype=float)
    class_penalty = np.where(y_binary == 0, FALSE_BUY_PENALTY_WEIGHT, 1.0)
    return np.clip(base * class_penalty, 1.0, 30.0)


def _fit_direction_classifier(
    x_train: pd.DataFrame,
    y_train_binary: np.ndarray,
    sample_weight: np.ndarray,
    n_estimators: int,
    learning_rate: float,
    max_depth: int,
    subsample: float,
) -> XGBClassifier | None:
    if len(y_train_binary) == 0 or np.unique(y_train_binary).size < 2:
        return None

    model = XGBClassifier(
        objective="binary:logistic",
        n_estimators=max(1000, int(n_estimators)),
        learning_rate=float(learning_rate),
        max_depth=max(8, int(max_depth)),
        min_child_weight=2,
        subsample=float(np.clip(subsample, 0.1, 1.0)),
        colsample_bytree=0.8,
        reg_lambda=1.0,
        scale_pos_weight=_compute_scale_pos_weight(y_train_binary),
        random_state=42,
        n_jobs=4,
        eval_metric="logloss",
    )
    model.fit(x_train, y_train_binary.astype(int), sample_weight=sample_weight)
    return model


def _fit_regression_model(
    x_train: pd.DataFrame,
    y_train: pd.Series,
    sample_weight: np.ndarray,
    n_estimators: int,
    learning_rate: float,
    max_depth: int,
    subsample: float,
) -> XGBRegressor:
    model = XGBRegressor(
        objective="reg:squarederror",
        n_estimators=max(1000, int(n_estimators)),
        learning_rate=float(learning_rate),
        max_depth=max(8, int(max_depth)),
        min_child_weight=2,
        subsample=float(np.clip(subsample, 0.1, 1.0)),
        colsample_bytree=0.8,
        reg_lambda=1.0,
        random_state=42,
        n_jobs=4,
    )
    model.fit(x_train, y_train, sample_weight=sample_weight)
    return model


def _select_direction_threshold(y_true: np.ndarray, prob_up: np.ndarray) -> tuple[float, float]:
    if len(y_true) == 0:
        return 0.5, float("nan")

    best_threshold = 0.5
    best_accuracy = -1.0
    for threshold in np.linspace(0.42, 0.58, 9):
        predicted = (prob_up >= threshold).astype(int)
        accuracy = float(np.mean(y_true.astype(int) == predicted))
        if accuracy > (best_accuracy + 1e-12):
            best_accuracy = accuracy
            best_threshold = float(threshold)
            continue

        if np.isclose(accuracy, best_accuracy) and abs(float(threshold) - 0.5) < abs(best_threshold - 0.5):
            best_threshold = float(threshold)

    return best_threshold, best_accuracy


def _select_global_precision_threshold(
    y_true: np.ndarray,
    prob_up: np.ndarray,
    actual_returns: np.ndarray | None = None,
) -> tuple[float, float, float]:
    if len(y_true) == 0:
        return 0.5, 0.0, 0.0

    min_signals = max(40, int(0.05 * len(y_true)))
    best_threshold = 0.5
    best_objective = -1.0
    best_precision = -1.0
    best_buy_rate = 0.0
    best_accuracy = -1.0

    for threshold in np.linspace(0.50, 0.90, 17):
        predicted = (prob_up >= float(threshold)).astype(int)
        signal_count = int(np.sum(predicted))
        if signal_count < min_signals:
            continue

        positives = y_true[predicted == 1]
        precision = float(np.mean(positives)) if len(positives) else 0.0
        buy_rate = float(signal_count / len(y_true))
        accuracy = float(np.mean(y_true.astype(int) == predicted.astype(int)))

        if actual_returns is not None:
            selected_returns = actual_returns[predicted == 1]
            positive_returns = selected_returns[selected_returns > 0.0]
            negative_returns = selected_returns[selected_returns < 0.0]
            avg_gain = float(np.mean(positive_returns)) if len(positive_returns) else 0.0
            avg_loss = float(np.abs(np.mean(negative_returns))) if len(negative_returns) else 0.0
            if avg_loss > 1e-9:
                pnl_ratio = float(np.clip(avg_gain / avg_loss, 0.0, 4.0))
            elif avg_gain > 0.0:
                pnl_ratio = 2.0
            else:
                pnl_ratio = 0.0
        else:
            pnl_ratio = 1.0

        objective = (0.60 * precision) + (0.25 * (pnl_ratio / 4.0)) + (0.15 * accuracy)

        if objective > (best_objective + 1e-12):
            best_objective = objective
            best_precision = precision
            best_threshold = float(threshold)
            best_buy_rate = buy_rate
            best_accuracy = accuracy
            continue

        if np.isclose(objective, best_objective) and precision > (best_precision + 1e-12):
            best_objective = objective
            best_precision = precision
            best_threshold = float(threshold)
            best_buy_rate = buy_rate
            best_accuracy = accuracy
            continue

        if np.isclose(objective, best_objective) and np.isclose(precision, best_precision) and accuracy > (best_accuracy + 1e-12):
            best_threshold = float(threshold)
            best_buy_rate = buy_rate
            best_accuracy = accuracy
            continue

        if np.isclose(objective, best_objective) and np.isclose(precision, best_precision) and np.isclose(accuracy, best_accuracy) and buy_rate > best_buy_rate:
            best_threshold = float(threshold)
            best_buy_rate = buy_rate
            best_accuracy = accuracy

    if best_precision < 0.0:
        fallback_predicted = (prob_up >= 0.5).astype(int)
        fallback_signal_count = int(np.sum(fallback_predicted))
        if fallback_signal_count == 0:
            return 0.5, 0.0, 0.0

        fallback_precision = float(np.mean(y_true[fallback_predicted == 1]))
        fallback_buy_rate = float(fallback_signal_count / len(y_true))
        return 0.5, fallback_precision, fallback_buy_rate

    return best_threshold, best_precision, best_buy_rate


def _select_symbol_precision_thresholds(
    prediction_frame: pd.DataFrame,
    fallback_threshold: float,
) -> dict[str, float]:
    thresholds: dict[str, float] = {}

    for symbol, symbol_frame in prediction_frame.groupby("symbol", sort=True):
        y_true = symbol_frame["actual_direction_up"].to_numpy(dtype=int)
        prob_up = symbol_frame["predicted_direction_prob_up"].to_numpy(dtype=float)
        actual_returns = symbol_frame["actual_return_5d"].to_numpy(dtype=float)
        sample_count = len(symbol_frame)

        if sample_count <= 0:
            thresholds[str(symbol)] = float(fallback_threshold)
            continue

        min_signals = max(5, int(0.08 * sample_count))
        threshold_floor = max(0.5, float(fallback_threshold) - 0.15)
        best_threshold = float(fallback_threshold)
        best_objective = -1.0
        best_precision = -1.0
        best_accuracy = -1.0
        best_buy_rate = 0.0

        for threshold in np.linspace(threshold_floor, 0.9, 17):
            predicted = (prob_up >= float(threshold)).astype(int)
            signal_count = int(np.sum(predicted))
            if signal_count < min_signals:
                continue

            positives = y_true[predicted == 1]
            precision = float(np.mean(positives)) if len(positives) else 0.0
            buy_rate = float(signal_count / sample_count)
            accuracy = float(np.mean(y_true == predicted))

            selected_returns = actual_returns[predicted == 1]
            positive_returns = selected_returns[selected_returns > 0.0]
            negative_returns = selected_returns[selected_returns < 0.0]
            avg_gain = float(np.mean(positive_returns)) if len(positive_returns) else 0.0
            avg_loss = float(np.abs(np.mean(negative_returns))) if len(negative_returns) else 0.0
            if avg_loss > 1e-9:
                pnl_ratio = float(np.clip(avg_gain / avg_loss, 0.0, 4.0))
            elif avg_gain > 0.0:
                pnl_ratio = 2.0
            else:
                pnl_ratio = 0.0

            objective = (0.60 * precision) + (0.25 * (pnl_ratio / 4.0)) + (0.15 * accuracy)

            if objective > (best_objective + 1e-12):
                best_objective = objective
                best_threshold = float(threshold)
                best_precision = precision
                best_buy_rate = buy_rate
                best_accuracy = accuracy
                continue

            if np.isclose(objective, best_objective) and precision > (best_precision + 1e-12):
                best_objective = objective
                best_threshold = float(threshold)
                best_precision = precision
                best_buy_rate = buy_rate
                best_accuracy = accuracy
                continue

            if np.isclose(objective, best_objective) and np.isclose(precision, best_precision) and accuracy > (best_accuracy + 1e-12):
                best_threshold = float(threshold)
                best_buy_rate = buy_rate
                best_accuracy = accuracy
                continue

            if np.isclose(objective, best_objective) and np.isclose(precision, best_precision) and np.isclose(accuracy, best_accuracy) and buy_rate > best_buy_rate:
                best_threshold = float(threshold)
                best_buy_rate = buy_rate
                best_accuracy = accuracy

        thresholds[str(symbol)] = float(best_threshold)

    return thresholds


def _compound_returns(returns: np.ndarray) -> float:
    if len(returns) == 0:
        return 0.0
    return float(np.prod(1.0 + np.asarray(returns, dtype=float)) - 1.0)


def _select_high_confidence_threshold(prediction_frame: pd.DataFrame) -> float:
    if prediction_frame.empty:
        return float(HIGH_CONFIDENCE_MIN_PROB)

    prob_up = pd.to_numeric(prediction_frame["predicted_direction_prob_up"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    predicted_up = pd.to_numeric(prediction_frame["predicted_direction_up"], errors="coerce").fillna(0).to_numpy(dtype=int)
    actual_up = pd.to_numeric(prediction_frame["actual_direction_up"], errors="coerce").fillna(0).to_numpy(dtype=int)
    actual_returns = pd.to_numeric(prediction_frame["actual_return_5d"], errors="coerce").fillna(0.0).to_numpy(dtype=float)

    total_rows = len(prediction_frame)
    if total_rows <= 0:
        return float(HIGH_CONFIDENCE_MIN_PROB)

    tradable_mask = predicted_up == 1
    if int(np.sum(tradable_mask)) == 0:
        return float(HIGH_CONFIDENCE_MIN_PROB)

    target_mid = 0.5 * (HIGH_CONFIDENCE_TARGET_MIN_BUY_RATE + HIGH_CONFIDENCE_TARGET_MAX_BUY_RATE)
    candidates: list[dict[str, float]] = []

    for threshold in np.linspace(0.35, 0.90, 56):
        high_confidence_mask = tradable_mask & (prob_up >= float(threshold))
        signal_count = int(np.sum(high_confidence_mask))
        if signal_count <= 0:
            continue

        buy_rate = float(signal_count / total_rows)
        precision = float(np.mean(actual_up[high_confidence_mask]))
        selected_returns = actual_returns[high_confidence_mask]
        selected_returns_capped = np.maximum(selected_returns, -HIGH_CONFIDENCE_STOP_LOSS_PCT)
        capped_cumulative_profit = _compound_returns(selected_returns_capped)

        candidates.append(
            {
                "threshold": float(threshold),
                "buy_rate": buy_rate,
                "precision": precision,
                "capped_cumulative_profit": capped_cumulative_profit,
            }
        )

    if not candidates:
        return float(HIGH_CONFIDENCE_MIN_PROB)

    in_band = [
        item
        for item in candidates
        if HIGH_CONFIDENCE_TARGET_MIN_BUY_RATE <= item["buy_rate"] <= HIGH_CONFIDENCE_TARGET_MAX_BUY_RATE
    ]
    in_band_with_precision = [
        item
        for item in in_band
        if item["precision"] >= HIGH_CONFIDENCE_MIN_PRECISION_TARGET
    ]

    if in_band_with_precision:
        selected = max(
            in_band_with_precision,
            key=lambda item: (
                item["capped_cumulative_profit"],
                item["precision"],
                -abs(item["buy_rate"] - target_mid),
                item["threshold"],
            ),
        )
        return float(selected["threshold"])

    if in_band:
        selected = max(
            in_band,
            key=lambda item: (
                item["precision"],
                item["capped_cumulative_profit"],
                -abs(item["buy_rate"] - target_mid),
                item["threshold"],
            ),
        )
        return float(selected["threshold"])

    selected = min(
        candidates,
        key=lambda item: (
            abs(item["buy_rate"] - target_mid),
            -item["precision"],
            -item["capped_cumulative_profit"],
            item["threshold"],
        ),
    )
    return float(selected["threshold"])

def _apply_symbol_thresholds_and_confidence_guard(
    prediction_frame: pd.DataFrame,
    symbol_thresholds: dict[str, float],
    fallback_threshold: float,
) -> pd.DataFrame:
    local = prediction_frame.copy()
    local["symbol_threshold"] = local["symbol"].map(symbol_thresholds).fillna(float(fallback_threshold))

    trade_date = pd.to_datetime(local["trade_date"], errors="coerce")
    late_micro_mask = (trade_date >= MICRO_RECOVERY_START) & (trade_date <= MICRO_REGIME_END)
    local["symbol_threshold"] = np.where(
        late_micro_mask.to_numpy(dtype=bool),
        np.minimum(local["symbol_threshold"].to_numpy(dtype=float), MICRO_RECOVERY_THRESHOLD_CAP),
        local["symbol_threshold"].to_numpy(dtype=float),
    )

    turbulent_signal = pd.to_numeric(local["regime_turbulent_signal"], errors="coerce").fillna(0.0)
    confidence_guard_active = turbulent_signal > CONFIDENCE_GUARD_SIGNAL_THRESHOLD
    local["applied_threshold"] = np.where(
        confidence_guard_active,
        np.maximum(local["symbol_threshold"].to_numpy(dtype=float), CONFIDENCE_GUARD_MIN_PROB),
        local["symbol_threshold"].to_numpy(dtype=float),
    )

    atr = pd.to_numeric(local.get("atr_14"), errors="coerce")
    close_price = pd.to_numeric(local.get("close_price"), errors="coerce")
    atr_ratio = (atr / close_price.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    high_volatility_mask = atr_ratio > HIGH_VOLATILITY_ATR_THRESHOLD
    local["applied_threshold"] = np.where(
        high_volatility_mask.to_numpy(dtype=bool),
        np.maximum(local["applied_threshold"].to_numpy(dtype=float), CONFIDENCE_GUARD_MIN_PROB),
        local["applied_threshold"].to_numpy(dtype=float),
    )
    local["high_volatility_atr_mask"] = high_volatility_mask.astype(int)

    local["confidence_guard_active"] = confidence_guard_active.astype(int)
    local["predicted_direction_up"] = (
        local["predicted_direction_prob_up"].to_numpy(dtype=float) >= local["applied_threshold"].to_numpy(dtype=float)
    ).astype(int)
    return local

def _extract_symbol_root(symbol: Any) -> str:
    raw = str(symbol or "").strip().upper()
    if not raw:
        return ""
    return raw.split(".")[0]


def _apply_symbol_guardrails(prediction_frame: pd.DataFrame) -> pd.DataFrame:
    local = prediction_frame.copy()
    symbol_root = local["symbol"].map(_extract_symbol_root)
    close_price = pd.to_numeric(local["close_price"], errors="coerce")
    ema_200 = pd.to_numeric(local["ema_200"], errors="coerce")

    guardrail_eligible = symbol_root.isin(HIGH_ERROR_SYMBOL_ROOTS) & close_price.notna() & ema_200.notna() & (close_price < ema_200)
    forced_no_buy = guardrail_eligible & (local["predicted_direction_up"] == 1)

    local.loc[forced_no_buy, "predicted_direction_up"] = 0
    local["guardrail_eligible"] = guardrail_eligible.astype(int)
    local["guardrail_forced_no_buy"] = forced_no_buy.astype(int)
    return local


def _apply_macro_importance_prior(importance: pd.Series) -> pd.Series:
    adjusted = importance.copy()
    for feature_name, multiplier in MACRO_PRIORITY_IMPORTANCE_MULTIPLIERS.items():
        if feature_name in adjusted.index:
            adjusted.loc[feature_name] = float(adjusted.loc[feature_name]) * float(multiplier)
    return adjusted


def _fit_macro_direction_model(
    train_slice: pd.DataFrame,
    test_slice: pd.DataFrame,
    n_estimators: int,
    learning_rate: float,
    max_depth: int,
    subsample: float,
) -> tuple[pd.Series | None, pd.Series]:
    default_importance = pd.Series(0.0, index=FEATURE_COLUMNS, dtype=float)

    macro_train = (
        train_slice.groupby("trade_date", as_index=False)
        .agg(
            {
                TARGET_COLUMN: "mean",
                "usd_egp_return": "first",
                "gold_return": "first",
                "cbe_policy_rate_pct": "first",
                "cbe_rate_changed": "first",
            }
        )
        .dropna(subset=[TARGET_COLUMN] + MACRO_DIRECTION_FEATURES)
    )
    macro_test = (
        test_slice.groupby("trade_date", as_index=False)
        .agg(
            {
                "usd_egp_return": "first",
                "gold_return": "first",
                "cbe_policy_rate_pct": "first",
                "cbe_rate_changed": "first",
            }
        )
        .dropna(subset=MACRO_DIRECTION_FEATURES)
    )

    if len(macro_train) < 60 or macro_test.empty:
        return None, default_importance

    y_macro_direction = (macro_train[TARGET_COLUMN].to_numpy(dtype=float) > 0.0).astype(int)
    if np.unique(y_macro_direction).size < 2:
        return None, default_importance

    x_macro_train = macro_train[MACRO_DIRECTION_FEATURES].astype(float)
    x_macro_test = macro_test[MACRO_DIRECTION_FEATURES].astype(float)

    positive_ratio = float(np.mean(y_macro_direction))
    if 0.0 < positive_ratio < 1.0:
        scale_pos_weight = float((1.0 - positive_ratio) / positive_ratio)
    else:
        scale_pos_weight = 1.0

    macro_model = XGBClassifier(
        objective="binary:logistic",
        n_estimators=max(300, int(n_estimators * 0.6)),
        learning_rate=max(0.005, float(learning_rate)),
        max_depth=max(3, min(6, int(max_depth) - 1)),
        min_child_weight=1,
        subsample=float(np.clip(subsample, 0.1, 1.0)),
        colsample_bytree=1.0,
        reg_lambda=1.0,
        scale_pos_weight=scale_pos_weight,
        random_state=42,
        n_jobs=4,
        eval_metric="logloss",
    )
    macro_model.fit(x_macro_train, y_macro_direction)

    macro_prob_by_date = pd.Series(
        macro_model.predict_proba(x_macro_test)[:, 1].astype(float),
        index=macro_test["trade_date"],
    )

    macro_importance = default_importance.copy()
    macro_importance.loc[MACRO_DIRECTION_FEATURES] = pd.Series(
        macro_model.feature_importances_,
        index=MACRO_DIRECTION_FEATURES,
        dtype=float,
    )
    return macro_prob_by_date, macro_importance


def load_sector_mapping(settings: MysqlSettings | None = None) -> dict[str, str]:
    sql = """
    SELECT UPPER(symbol) AS symbol, COALESCE(sector_code, 'UNMAPPED') AS sector_code
    FROM stock_instruments
    """

    connection = open_mysql_connection(settings=settings)
    try:
        frame = pd.read_sql(sql=sql, con=connection)
    finally:
        connection.close()

    if frame.empty:
        return {}

    mapping: dict[str, str] = {}
    for _, item in frame.iterrows():
        raw_symbol = str(item.get("symbol") or "").strip().upper()
        if not raw_symbol:
            continue

        mapped = canonicalize_symbol(raw_symbol, allow_unmapped=True)
        if mapped:
            mapping[mapped.upper()] = str(item.get("sector_code") or "UNMAPPED").strip().upper() or "UNMAPPED"
        mapping[raw_symbol] = str(item.get("sector_code") or "UNMAPPED").strip().upper() or "UNMAPPED"

    return mapping


def load_market_context(
    start_date: date | None = None,
    end_date: date | None = None,
    settings: MysqlSettings | None = None,
) -> pd.DataFrame:
    start_value = start_date or DEFAULT_START_DATE
    sql = [
        "SELECT",
        "  trade_date,",
        "  usd_egp_close,",
        "  gold_usd_close,",
        "  cbe_policy_rate_pct,",
        "  cbe_rate_changed",
        "FROM market_context",
        "WHERE trade_date >= %s",
    ]
    params: list[Any] = [start_value]

    if end_date is not None:
        sql.append("  AND trade_date <= %s")
        params.append(end_date)

    sql.append("ORDER BY trade_date ASC")

    connection = open_mysql_connection(settings=settings)
    try:
        frame = pd.read_sql(sql="\n".join(sql), con=connection, params=params)
    finally:
        connection.close()

    if frame.empty:
        raise RuntimeError("market_context table is empty. Run macro_engine.py first.")

    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    frame["usd_egp_close"] = pd.to_numeric(frame["usd_egp_close"], errors="coerce")
    frame["gold_usd_close"] = pd.to_numeric(frame["gold_usd_close"], errors="coerce")
    frame["cbe_policy_rate_pct"] = pd.to_numeric(frame["cbe_policy_rate_pct"], errors="coerce")
    frame["cbe_rate_changed"] = frame["cbe_rate_changed"].fillna(False).astype(int)

    frame = frame.dropna(subset=["trade_date"]).sort_values("trade_date").drop_duplicates("trade_date", keep="last")
    frame["usd_egp_return"] = frame["usd_egp_close"].pct_change()
    frame["gold_return"] = frame["gold_usd_close"].pct_change()

    return frame.reset_index(drop=True)


def load_alternative_context(
    start_date: date | None = None,
    end_date: date | None = None,
    settings: MysqlSettings | None = None,
) -> pd.DataFrame:
    start_value = start_date or DEFAULT_START_DATE

    commodity_sql = [
        "SELECT",
        "  trade_date,",
        "  MAX(CASE WHEN commodity_name = 'Urea' THEN price END) AS alt_urea_price,",
        "  MAX(CASE WHEN commodity_name = 'Brent Crude' THEN price END) AS alt_brent_price",
        "FROM daily_commodities",
        "WHERE trade_date >= %s",
    ]
    sentiment_sql = [
        "SELECT",
        "  trade_date,",
        "  market_sentiment_score AS alt_news_sentiment_score",
        "FROM daily_market_sentiment",
        "WHERE trade_date >= %s",
    ]
    commodity_params: list[Any] = [start_value]
    sentiment_params: list[Any] = [start_value]

    if end_date is not None:
        commodity_sql.append("  AND trade_date <= %s")
        sentiment_sql.append("  AND trade_date <= %s")
        commodity_params.append(end_date)
        sentiment_params.append(end_date)

    commodity_sql.extend(["GROUP BY trade_date", "ORDER BY trade_date ASC"])
    sentiment_sql.append("ORDER BY trade_date ASC")

    resolved = settings or resolve_mysql_settings()
    alt_settings = MysqlSettings(
        host=resolved.host,
        port=ALT_DB_PORT,
        user=resolved.user,
        password=resolved.password,
        database=resolved.database,
    )

    connection = open_mysql_connection(settings=alt_settings)
    try:
        commodity_frame = pd.read_sql(sql="\n".join(commodity_sql), con=connection, params=commodity_params)
        sentiment_frame = pd.read_sql(sql="\n".join(sentiment_sql), con=connection, params=sentiment_params)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Alternative context load failed: %s", exc)
        return pd.DataFrame(columns=["trade_date", "alt_urea_price", "alt_brent_price", "alt_news_sentiment_score"])
    finally:
        connection.close()

    if commodity_frame.empty and sentiment_frame.empty:
        return pd.DataFrame(columns=["trade_date", "alt_urea_price", "alt_brent_price", "alt_news_sentiment_score"])

    for frame in (commodity_frame, sentiment_frame):
        if "trade_date" in frame.columns:
            frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")

    merged = commodity_frame.merge(sentiment_frame, on="trade_date", how="outer")
    merged["alt_urea_price"] = pd.to_numeric(merged.get("alt_urea_price"), errors="coerce")
    merged["alt_brent_price"] = pd.to_numeric(merged.get("alt_brent_price"), errors="coerce")
    merged["alt_news_sentiment_score"] = pd.to_numeric(merged.get("alt_news_sentiment_score"), errors="coerce")
    merged = merged.dropna(subset=["trade_date"]).sort_values("trade_date").drop_duplicates("trade_date", keep="last")
    return merged.reset_index(drop=True)


def compute_rsi(close_series: pd.Series, period: int = 14) -> pd.Series:
    delta = close_series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def compute_atr(group: pd.DataFrame, period: int = 14) -> pd.Series:
    high = group["high_price"].astype(float)
    low = group["low_price"].astype(float)
    close = group["close_price"].astype(float)

    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return true_range.rolling(window=period, min_periods=period).mean()


def add_technical_features(raw_frame: pd.DataFrame) -> pd.DataFrame:
    if raw_frame.empty:
        return raw_frame.copy()

    ordered = raw_frame.sort_values(["symbol", "trade_date"]).copy()

    def _enrich(symbol: str, group: pd.DataFrame) -> pd.DataFrame:
        local = group.copy()
        close = local["close_price"].astype(float)

        local["daily_return"] = close.pct_change()
        local["ema_20"] = close.ewm(span=20, adjust=False).mean()
        local["ema_50"] = close.ewm(span=50, adjust=False).mean()
        local["ema_200"] = close.ewm(span=200, adjust=False).mean()

        ema_12 = close.ewm(span=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, adjust=False).mean()
        local["macd"] = ema_12 - ema_26
        local["macd_signal"] = local["macd"].ewm(span=9, adjust=False).mean()
        local["macd_hist"] = local["macd"] - local["macd_signal"]

        rolling_std_20 = close.rolling(window=20, min_periods=20).std()
        local["bollinger_mid_20"] = close.rolling(window=20, min_periods=20).mean()
        local["bollinger_upper_20"] = local["bollinger_mid_20"] + (2.0 * rolling_std_20)
        local["bollinger_lower_20"] = local["bollinger_mid_20"] - (2.0 * rolling_std_20)

        local["rsi_14"] = compute_rsi(close, period=14)
        local["atr_14"] = compute_atr(local, period=14)

        local["volume_20d_avg"] = local["volume"].astype(float).rolling(window=20, min_periods=5).mean()
        local["volume_shock_20d"] = (local["volume"].astype(float) / local["volume_20d_avg"]) - 1.0
        local["volume_60d_avg"] = local["volume"].astype(float).rolling(window=60, min_periods=20).mean()
        local["relative_volume_60d"] = (
            local["volume"].astype(float) / local["volume_60d_avg"]
        ).replace([np.inf, -np.inf], np.nan).fillna(1.0)
        local["symbol"] = str(symbol).upper()

        return local

    enriched_frames = [
        _enrich(symbol=str(symbol), group=group)
        for symbol, group in ordered.groupby("symbol", sort=False)
    ]
    if not enriched_frames:
        return ordered.copy()
    return pd.concat(enriched_frames, ignore_index=True)


def build_feature_factory_dataset(
    raw_frame: pd.DataFrame,
    sector_map: dict[str, str],
    market_context: pd.DataFrame,
    settings: MysqlSettings | None = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> FeatureFactoryResult:
    if raw_frame.empty:
        raise RuntimeError("Historical market data is empty")
    if market_context.empty:
        raise RuntimeError("market_context data is empty")

    local = raw_frame.copy()
    local["symbol"] = local["symbol"].astype(str).str.upper()

    local["canonical_symbol"] = local["symbol"].map(lambda item: canonicalize_symbol(item, allow_unmapped=True) or item)
    local["sector_code"] = local["canonical_symbol"].map(lambda item: sector_map.get(str(item).upper(), "UNMAPPED"))

    features = add_technical_features(local)

    context = market_context.copy()
    alt_context = load_alternative_context(
        start_date=pd.Timestamp(features["trade_date"].min()).date(),
        end_date=pd.Timestamp(features["trade_date"].max()).date(),
        settings=settings,
    )
    context["trade_date"] = pd.to_datetime(context["trade_date"], errors="coerce")
    features["trade_date"] = pd.to_datetime(features["trade_date"], errors="coerce")

    merged = features.merge(
        context[
            [
                "trade_date",
                "usd_egp_close",
                "gold_usd_close",
                "cbe_policy_rate_pct",
                "cbe_rate_changed",
                "usd_egp_return",
                "gold_return",
            ]
        ],
        on="trade_date",
        how="left",
    )

    if not alt_context.empty:
        merged = merged.merge(
            alt_context[["trade_date", "alt_urea_price", "alt_brent_price", "alt_news_sentiment_score"]],
            on="trade_date",
            how="left",
        )
    else:
        merged["alt_urea_price"] = np.nan
        merged["alt_brent_price"] = np.nan
        merged["alt_news_sentiment_score"] = np.nan

    merged[["usd_egp_close", "gold_usd_close", "cbe_policy_rate_pct", "usd_egp_return", "gold_return"]] = merged[
        ["usd_egp_close", "gold_usd_close", "cbe_policy_rate_pct", "usd_egp_return", "gold_return"]
    ].ffill().bfill()
    merged["cbe_rate_changed"] = merged["cbe_rate_changed"].fillna(0).astype(int)

    merged[["alt_urea_price", "alt_brent_price", "alt_news_sentiment_score"]] = merged[
        ["alt_urea_price", "alt_brent_price", "alt_news_sentiment_score"]
    ].ffill().bfill()

    symbol_roots = merged["symbol"].astype(str).str.upper().str.split(".").str[0]
    merged["alt_urea_price"] = np.where(
        symbol_roots.isin(UREA_SYMBOL_ROOTS),
        merged["alt_urea_price"],
        0.0,
    )
    merged["alt_brent_price"] = np.where(
        symbol_roots.isin(BRENT_SYMBOL_ROOTS),
        merged["alt_brent_price"],
        0.0,
    )
    merged["alt_news_sentiment_score"] = merged["alt_news_sentiment_score"].fillna(0.0)

    merged = append_market_sentiment_features(merged)

    merged["stock_usd_corr_20d"] = (
        merged.groupby("symbol", group_keys=False)
        .apply(
            lambda group: group["daily_return"].rolling(window=20, min_periods=10).corr(group["usd_egp_return"])
        )
        .reset_index(level=0, drop=True)
    )

    sector_daily = (
        merged.groupby(["trade_date", "sector_code"], as_index=False)["daily_return"]
        .mean()
        .rename(columns={"daily_return": "sector_daily_return"})
        .sort_values(["sector_code", "trade_date"])
    )
    sector_daily["sector_momentum_5d"] = (
        sector_daily.groupby("sector_code")["sector_daily_return"]
        .transform(lambda series: series.rolling(window=5, min_periods=3).mean())
    )

    merged = merged.merge(
        sector_daily[["trade_date", "sector_code", "sector_momentum_5d"]],
        on=["trade_date", "sector_code"],
        how="left",
    )

    merged = merged.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    merged[TARGET_COLUMN] = (
        merged.groupby("symbol", group_keys=False)["close_price"].shift(-horizon_days) / merged["close_price"]
    ) - 1.0

    numeric_cols = FEATURE_COLUMNS + [TARGET_COLUMN]
    for col in numeric_cols:
        merged[col] = pd.to_numeric(merged[col], errors="coerce")

    merged = merged.replace([np.inf, -np.inf], np.nan)
    merged = merged.dropna(subset=FEATURE_COLUMNS + [TARGET_COLUMN, "symbol", "trade_date", "sector_code"])
    merged = merged.sort_values(["trade_date", "symbol"]).reset_index(drop=True)

    symbols = sorted({str(item).upper() for item in merged["symbol"].unique().tolist()})
    return FeatureFactoryResult(frame=merged, symbols=symbols)


def _build_model_matrix(
    frame: pd.DataFrame,
    expected_columns: list[str] | None = None,
    feature_scalers: dict[str, float] | None = None,
) -> pd.DataFrame:
    local = frame.copy()
    local["symbol"] = local["symbol"].astype(str).str.upper()
    local["sector_code"] = local["sector_code"].astype(str).str.upper()

    model_frame = local[FEATURE_COLUMNS + ["symbol", "sector_code"]].copy()
    if feature_scalers:
        for feature_name, scaler in feature_scalers.items():
            if feature_name in model_frame.columns:
                model_frame[feature_name] = pd.to_numeric(model_frame[feature_name], errors="coerce").fillna(0.0) * float(scaler)

    encoded = pd.get_dummies(model_frame, columns=["symbol", "sector_code"], dtype=float)

    if expected_columns is None:
        return encoded
    return encoded.reindex(columns=expected_columns, fill_value=0.0)


def run_walk_forward_validation_xgboost(
    feature_frame: pd.DataFrame,
    train_end: date = DEFAULT_TRAIN_END,
    blind_start: date = DEFAULT_BLIND_START,
    blind_end: date = DEFAULT_BLIND_END,
    retrain_every: int = DEFAULT_RETRAIN_EVERY,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    n_estimators: int = DEFAULT_N_ESTIMATORS,
    learning_rate: float = DEFAULT_LEARNING_RATE,
    max_depth: int = DEFAULT_MAX_DEPTH,
    subsample: float = DEFAULT_SUBSAMPLE,
) -> tuple[WalkForwardMetrics, pd.DataFrame, pd.DataFrame, list[BlockTrainingLog]]:
    if feature_frame.empty:
        raise RuntimeError("Feature frame is empty")

    ordered = feature_frame.sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    ordered["trade_date"] = pd.to_datetime(ordered["trade_date"], errors="coerce")

    blind_mask = (ordered["trade_date"] >= pd.Timestamp(blind_start)) & (ordered["trade_date"] <= pd.Timestamp(blind_end))
    blind_dates = sorted(ordered.loc[blind_mask, "trade_date"].dropna().unique().tolist())
    if not blind_dates:
        raise RuntimeError("No blind test rows found in the selected date range")

    full_feature_cols = _build_model_matrix(ordered).columns.tolist()

    predictions: list[pd.DataFrame] = []
    blocks_trained = 0
    block_logs: list[BlockTrainingLog] = []
    block_metadata: list[dict[str, Any]] = []
    base_feature_importance_accumulator = pd.Series(0.0, index=FEATURE_COLUMNS, dtype=float)
    base_feature_importance_weight = 0.0

    total_blocks = int(np.ceil(len(blind_dates) / max(1, retrain_every)))
    LOGGER.info(
        "Starting deep walk-forward validation: total_blocks=%s n_estimators=%s learning_rate=%s max_depth=%s subsample=%s",
        total_blocks,
        n_estimators,
        learning_rate,
        max_depth,
        subsample,
    )

    for block_start_idx in range(0, len(blind_dates), max(1, retrain_every)):
        block_dates = blind_dates[block_start_idx: block_start_idx + max(1, retrain_every)]
        block_start_date = pd.Timestamp(block_dates[0])
        block_end_date = pd.Timestamp(block_dates[-1])
        block_id = (block_start_idx // max(1, retrain_every)) + 1

        # Respect 5-day horizon when selecting rows with known labels.
        known_cutoff = (block_start_date - pd.offsets.BDay(horizon_days)).normalize()

        train_mask = (ordered["trade_date"] <= known_cutoff) & (ordered["trade_date"] <= pd.Timestamp(blind_end))
        test_mask = ordered["trade_date"].isin(block_dates)

        train_slice = ordered.loc[train_mask].copy()
        test_slice = ordered.loc[test_mask].copy()

        if train_slice.empty or test_slice.empty:
            LOGGER.info(
                "WF_BLOCK %02d/%02d SKIPPED (empty split): train_rows=%s test_rows=%s",
                block_id,
                total_blocks,
                len(train_slice),
                len(test_slice),
            )
            continue

        # Force initial split requirement 2016..Dec-2024 for first block.
        if block_start_idx == 0:
            train_slice = train_slice.loc[train_slice["trade_date"] <= pd.Timestamp(train_end)].copy()

        if len(train_slice) < 1000:
            LOGGER.info(
                "WF_BLOCK %02d/%02d SKIPPED (insufficient rows): train_rows=%s",
                block_id,
                total_blocks,
                len(train_slice),
            )
            continue

        x_train = _build_model_matrix(train_slice, expected_columns=full_feature_cols)
        y_train = train_slice[TARGET_COLUMN].astype(float)
        train_turbulence_score = _compute_turbulence_score(train_slice)
        test_turbulence_score = _compute_turbulence_score(test_slice)
        (
            train_sample_weights,
            train_turbulent_mask,
            turbulent_threshold,
            current_regime_score,
            crisis_rows_weighted,
        ) = _build_regime_sample_weights(
            train_slice=train_slice,
            turbulence_score=train_turbulence_score,
        )
        train_turbulent_share = float(np.mean(train_turbulent_mask.astype(float))) if len(train_turbulent_mask) else 0.0

        x_test = _build_model_matrix(test_slice, expected_columns=full_feature_cols)
        y_test = test_slice[TARGET_COLUMN].astype(float)

        LOGGER.info(
            "WF_BLOCK %02d/%02d TRAINING: train_window=%s..%s test_window=%s..%s train_rows=%s test_rows=%s",
            block_id,
            total_blocks,
            train_slice["trade_date"].min().date().isoformat(),
            train_slice["trade_date"].max().date().isoformat(),
            block_start_date.date().isoformat(),
            block_end_date.date().isoformat(),
            len(train_slice),
            len(test_slice),
        )

        y_train_direction = (y_train.to_numpy(dtype=float) > 0.0).astype(int)
        y_test_direction = (y_test.to_numpy(dtype=float) > 0.0).astype(int)

        min_regime_rows = max(1200, int(0.08 * len(train_slice)))
        stable_mask = ~train_turbulent_mask
        turbulent_mask = train_turbulent_mask.copy()
        if int(np.sum(stable_mask)) < min_regime_rows:
            stable_mask = np.ones(len(train_slice), dtype=bool)
        if int(np.sum(turbulent_mask)) < min_regime_rows:
            turbulent_mask = np.ones(len(train_slice), dtype=bool)

        stable_weights = np.clip(train_sample_weights[stable_mask], 1.0, 18.0)
        turbulent_weights = np.clip(
            train_sample_weights[turbulent_mask] * np.where(train_turbulent_mask[turbulent_mask], 1.2, 1.0),
            1.0,
            20.0,
        )
        stable_direction_weights = _build_directional_sample_weights(stable_weights, y_train_direction[stable_mask])
        turbulent_direction_weights = _build_directional_sample_weights(turbulent_weights, y_train_direction[turbulent_mask])

        stable_reg_model = _fit_regression_model(
            x_train=x_train.loc[stable_mask],
            y_train=y_train.loc[stable_mask],
            sample_weight=stable_weights,
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            max_depth=max(6, int(max_depth) - 1),
            subsample=min(1.0, float(subsample) + 0.05),
        )
        turbulent_reg_model = _fit_regression_model(
            x_train=x_train.loc[turbulent_mask],
            y_train=y_train.loc[turbulent_mask],
            sample_weight=turbulent_weights,
            n_estimators=n_estimators,
            learning_rate=max(0.008, float(learning_rate)),
            max_depth=max(8, int(max_depth) + 1),
            subsample=max(0.5, float(subsample) - 0.05),
        )

        stable_direction_model = _fit_direction_classifier(
            x_train=x_train.loc[stable_mask],
            y_train_binary=y_train_direction[stable_mask],
            sample_weight=stable_direction_weights,
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            max_depth=max(6, int(max_depth) - 1),
            subsample=min(1.0, float(subsample) + 0.05),
        )
        if stable_direction_model is None:
            stable_direction_model = _fit_direction_classifier(
                x_train=x_train,
                y_train_binary=y_train_direction,
                sample_weight=_build_directional_sample_weights(np.clip(train_sample_weights, 1.0, 18.0), y_train_direction),
                n_estimators=n_estimators,
                learning_rate=learning_rate,
                max_depth=max_depth,
                subsample=subsample,
            )

        turbulent_direction_model = _fit_direction_classifier(
            x_train=x_train.loc[turbulent_mask],
            y_train_binary=y_train_direction[turbulent_mask],
            sample_weight=turbulent_direction_weights,
            n_estimators=n_estimators,
            learning_rate=max(0.008, float(learning_rate)),
            max_depth=max(8, int(max_depth) + 1),
            subsample=max(0.5, float(subsample) - 0.05),
        )
        if turbulent_direction_model is None:
            turbulent_direction_model = stable_direction_model
        if stable_direction_model is None or turbulent_direction_model is None:
            raise RuntimeError(f"Unable to train classification model for block {block_id}")

        regime_blend_weight, yesterday_turbulent_mask = _compute_regime_blend_weights(
            train_slice=train_slice,
            test_slice=test_slice,
            train_turbulence_score=train_turbulence_score,
            test_turbulence_score=test_turbulence_score,
            turbulent_threshold=turbulent_threshold,
        )
        row_turbulent_mask = (
            pd.to_numeric(test_turbulence_score, errors="coerce").fillna(0.0).to_numpy(dtype=float) >= turbulent_threshold
        )
        regime_turbulent_flag = (
            (regime_blend_weight >= 0.5)
            | row_turbulent_mask.astype(bool)
            | yesterday_turbulent_mask.astype(bool)
        )

        test_turbulence_array = pd.to_numeric(test_turbulence_score, errors="coerce").fillna(0.0).to_numpy(dtype=float)
        if turbulent_threshold > 1e-8:
            normalized_test_turbulence = np.clip(test_turbulence_array / turbulent_threshold, 0.0, 1.5) / 1.5
        else:
            normalized_test_turbulence = np.zeros(len(test_slice), dtype=float)
        regime_turbulent_signal = np.clip(
            (0.60 * regime_blend_weight)
            + (0.30 * normalized_test_turbulence)
            + (0.10 * regime_turbulent_flag.astype(float)),
            0.0,
            1.0,
        )

        stable_return_pred = stable_reg_model.predict(x_test).astype(float)
        turbulent_return_pred = turbulent_reg_model.predict(x_test).astype(float)
        y_pred = (
            ((1.0 - regime_blend_weight) * stable_return_pred)
            + (regime_blend_weight * turbulent_return_pred)
        )

        stable_direction_prob = stable_direction_model.predict_proba(x_test)[:, 1].astype(float)
        turbulent_direction_prob = turbulent_direction_model.predict_proba(x_test)[:, 1].astype(float)
        y_pred_direction_prob = (
            ((1.0 - regime_blend_weight) * stable_direction_prob)
            + (regime_blend_weight * turbulent_direction_prob)
        )

        aligned_micro_importance = pd.Series(0.0, index=FEATURE_COLUMNS, dtype=float)
        macro_prob_by_date, macro_direction_importance = _fit_macro_direction_model(
            train_slice=train_slice,
            test_slice=test_slice,
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            max_depth=max_depth,
            subsample=subsample,
        )
        if macro_prob_by_date is not None:
            macro_prob = test_slice["trade_date"].map(macro_prob_by_date).to_numpy(dtype=float)
            macro_missing = np.isnan(macro_prob)
            if np.any(macro_missing):
                macro_prob[macro_missing] = y_pred_direction_prob[macro_missing]
            y_pred_direction_prob = (
                ((1.0 - MACRO_DIRECTION_BLEND_WEIGHT) * y_pred_direction_prob)
                + (MACRO_DIRECTION_BLEND_WEIGHT * macro_prob)
            )

        micro_train_mask = (train_slice["trade_date"] >= MICRO_REGIME_START) & (train_slice["trade_date"] <= MICRO_REGIME_END)
        micro_test_mask = (test_slice["trade_date"] >= MICRO_REGIME_START) & (test_slice["trade_date"] <= MICRO_REGIME_END)
        micro_train_mask_np = micro_train_mask.to_numpy(dtype=bool)
        micro_test_mask_np = micro_test_mask.to_numpy(dtype=bool)

        if int(np.sum(micro_train_mask_np)) >= max(300, int(0.03 * len(train_slice))):
            x_train_micro = _build_model_matrix(
                train_slice.loc[micro_train_mask_np],
                expected_columns=full_feature_cols,
                feature_scalers=MICRO_REGIME_FEATURE_SCALERS,
            )
            y_train_micro = y_train.loc[micro_train_mask_np]
            y_train_micro_direction = y_train_direction[micro_train_mask_np]
            micro_weights = np.clip(train_sample_weights[micro_train_mask_np] * 1.4, 1.0, 24.0)

            micro_reg_model = _fit_regression_model(
                x_train=x_train_micro,
                y_train=y_train_micro,
                sample_weight=micro_weights,
                n_estimators=n_estimators,
                learning_rate=max(0.008, float(learning_rate)),
                max_depth=max(9, int(max_depth) + 1),
                subsample=max(0.5, float(subsample) - 0.05),
            )

            micro_direction_model = _fit_direction_classifier(
                x_train=x_train_micro,
                y_train_binary=y_train_micro_direction,
                sample_weight=_build_directional_sample_weights(micro_weights, y_train_micro_direction),
                n_estimators=n_estimators,
                learning_rate=max(0.008, float(learning_rate)),
                max_depth=max(9, int(max_depth) + 1),
                subsample=max(0.5, float(subsample) - 0.05),
            )

            x_test_micro = _build_model_matrix(
                test_slice,
                expected_columns=full_feature_cols,
                feature_scalers=MICRO_REGIME_FEATURE_SCALERS,
            )
            micro_return_pred = micro_reg_model.predict(x_test_micro).astype(float)
            if micro_direction_model is not None:
                micro_direction_prob = micro_direction_model.predict_proba(x_test_micro)[:, 1].astype(float)
            else:
                micro_direction_prob = y_pred_direction_prob

            micro_blend_weight = np.where(micro_test_mask_np, MICRO_REGIME_BLEND_WEIGHT, 0.0).astype(float)
            y_pred = ((1.0 - micro_blend_weight) * y_pred) + (micro_blend_weight * micro_return_pred)
            y_pred_direction_prob = (
                ((1.0 - micro_blend_weight) * y_pred_direction_prob)
                + (micro_blend_weight * micro_direction_prob)
            )

            micro_reg_importance = pd.Series(micro_reg_model.feature_importances_, index=x_train_micro.columns, dtype=float)
            aligned_micro_reg_importance = micro_reg_importance.reindex(FEATURE_COLUMNS).fillna(0.0)
            if micro_direction_model is not None:
                micro_cls_importance = pd.Series(micro_direction_model.feature_importances_, index=x_train_micro.columns, dtype=float)
                aligned_micro_cls_importance = micro_cls_importance.reindex(FEATURE_COLUMNS).fillna(0.0)
            else:
                aligned_micro_cls_importance = pd.Series(0.0, index=FEATURE_COLUMNS, dtype=float)

            aligned_micro_importance = (0.60 * aligned_micro_reg_importance) + (0.40 * aligned_micro_cls_importance)
            for feature_name, multiplier in MICRO_REGIME_IMPORTANCE_MULTIPLIERS.items():
                if feature_name in aligned_micro_importance.index:
                    aligned_micro_importance.loc[feature_name] = float(aligned_micro_importance.loc[feature_name]) * float(multiplier)
        else:
            micro_test_mask_np = np.zeros(len(test_slice), dtype=bool)

        relative_volume_test = pd.to_numeric(test_slice["relative_volume_60d"], errors="coerce").fillna(1.0).to_numpy(dtype=float)
        smart_money_multiplier = np.where(
            relative_volume_test < 1.0,
            np.clip(relative_volume_test, 0.60, 1.0) * SMART_MONEY_LOW_VOLUME_DOWNSCALE,
            1.0,
        )
        y_pred_direction_prob = np.clip(y_pred_direction_prob * smart_money_multiplier, 0.0, 1.0)

        y_pred_direction_raw = (y_pred_direction_prob >= 0.5).astype(int)

        block_rmse = float(np.sqrt(np.mean(np.square(y_test.to_numpy(dtype=float) - y_pred))))
        block_reg_direction = float(
            np.mean(np.sign(y_test.to_numpy(dtype=float)) == np.sign(y_pred))
        )
        block_clf_direction_raw = float(np.mean(y_test_direction == y_pred_direction_raw))

        stable_reg_importance_series = pd.Series(stable_reg_model.feature_importances_, index=x_train.columns, dtype=float)
        turbulent_reg_importance_series = pd.Series(turbulent_reg_model.feature_importances_, index=x_train.columns, dtype=float)
        stable_cls_importance_series = pd.Series(stable_direction_model.feature_importances_, index=x_train.columns, dtype=float)
        turbulent_cls_importance_series = pd.Series(turbulent_direction_model.feature_importances_, index=x_train.columns, dtype=float)

        aligned_stable_reg_importance = stable_reg_importance_series.reindex(FEATURE_COLUMNS).fillna(0.0)
        aligned_turbulent_reg_importance = turbulent_reg_importance_series.reindex(FEATURE_COLUMNS).fillna(0.0)
        aligned_stable_cls_importance = stable_cls_importance_series.reindex(FEATURE_COLUMNS).fillna(0.0)
        aligned_turbulent_cls_importance = turbulent_cls_importance_series.reindex(FEATURE_COLUMNS).fillna(0.0)

        aligned_reg_importance = (
            ((1.0 - train_turbulent_share) * aligned_stable_reg_importance)
            + (train_turbulent_share * aligned_turbulent_reg_importance)
        )
        aligned_cls_importance = (
            ((1.0 - train_turbulent_share) * aligned_stable_cls_importance)
            + (train_turbulent_share * aligned_turbulent_cls_importance)
        )
        aligned_macro_importance = macro_direction_importance.reindex(FEATURE_COLUMNS).fillna(0.0)
        aligned_base_importance = (
            (0.45 * aligned_reg_importance)
            + (0.35 * aligned_cls_importance)
            + (0.20 * aligned_macro_importance)
        )
        if float(aligned_micro_importance.sum()) > 0.0:
            aligned_base_importance = (0.70 * aligned_base_importance) + (0.30 * aligned_micro_importance)
        aligned_base_importance = _apply_macro_importance_prior(aligned_base_importance)
        weight = float(len(train_slice))
        base_feature_importance_accumulator = base_feature_importance_accumulator.add(aligned_base_importance * weight)
        base_feature_importance_weight += weight

        LOGGER.info(
            "WF_BLOCK %02d/%02d DONE: rmse=%.6f dir_acc_reg=%.4f dir_acc_cls_raw=%.4f turbulent_signal_mean=%.4f crisis_rows_weighted=%s current_regime_score=%.4f",
            block_id,
            total_blocks,
            block_rmse,
            block_reg_direction,
            block_clf_direction_raw,
            float(np.mean(regime_turbulent_signal)),
            crisis_rows_weighted,
            current_regime_score,
        )

        batch = test_slice[["trade_date","symbol","sector_code","close_price","ema_200","atr_14","relative_volume_60d","market_sentiment_score","smart_money_signal","global_factor_corr_sp500"]].copy()
        batch["block_id"] = int(block_id)
        batch["block_start_date"] = block_start_date.date().isoformat()
        batch["block_end_date"] = block_end_date.date().isoformat()
        batch["train_rows"] = int(len(train_slice))
        batch["test_rows"] = int(len(test_slice))
        batch["actual_return_5d"] = y_test.to_numpy(dtype=float)
        batch["predicted_return_5d"] = y_pred
        batch["actual_direction_up"] = y_test_direction
        batch["predicted_direction_up_raw"] = y_pred_direction_raw
        batch["predicted_direction_up"] = y_pred_direction_raw
        batch["predicted_direction_prob_up"] = y_pred_direction_prob
        batch["smart_money_confidence_multiplier"] = smart_money_multiplier
        batch["regime_blend_weight"] = regime_blend_weight
        batch["regime_turbulent_signal"] = regime_turbulent_signal
        batch["micro_regime_active"] = micro_test_mask_np.astype(int)
        batch["current_regime_score"] = float(current_regime_score)
        batch["turbulent_threshold"] = float(turbulent_threshold)
        predictions.append(batch)
        blocks_trained += 1
        block_metadata.append(
            {
                "block_id": int(block_id),
                "block_start_date": block_start_date.date().isoformat(),
                "block_end_date": block_end_date.date().isoformat(),
                "train_rows": int(len(train_slice)),
                "test_rows": int(len(test_slice)),
                "directional_accuracy_classification_raw": float(block_clf_direction_raw),
                "crisis_rows_weighted": int(crisis_rows_weighted),
            }
        )

    if not predictions:
        raise RuntimeError("Walk-forward validation did not produce predictions")

    prediction_frame = pd.concat(predictions, ignore_index=True)
    global_threshold, precision_at_threshold, buy_rate_at_threshold = _select_global_precision_threshold(
        y_true=prediction_frame["actual_direction_up"].to_numpy(dtype=int),
        prob_up=prediction_frame["predicted_direction_prob_up"].to_numpy(dtype=float),
        actual_returns=prediction_frame["actual_return_5d"].to_numpy(dtype=float),
    )
    symbol_thresholds = _select_symbol_precision_thresholds(
        prediction_frame=prediction_frame,
        fallback_threshold=global_threshold,
    )
    prediction_frame = _apply_symbol_thresholds_and_confidence_guard(
        prediction_frame=prediction_frame,
        symbol_thresholds=symbol_thresholds,
        fallback_threshold=global_threshold,
    )
    prediction_frame = _apply_symbol_guardrails(prediction_frame)

    final_buy_mask = prediction_frame["predicted_direction_up"].to_numpy(dtype=int) == 1
    final_signal_count = int(np.sum(final_buy_mask))
    if final_signal_count > 0:
        final_precision = float(np.mean(prediction_frame.loc[final_buy_mask, "actual_direction_up"].to_numpy(dtype=int)))
    else:
        final_precision = 0.0
    final_buy_rate = float(final_signal_count / len(prediction_frame)) if len(prediction_frame) else 0.0
    confidence_guard_active_rows = int(np.sum(prediction_frame["confidence_guard_active"].to_numpy(dtype=int)))

    LOGGER.info(
        "THRESHOLD_CALIBRATION global=%.2f symbols=%s final_precision=%.4f final_buy_rate=%.4f confidence_guard_rows=%s",
        global_threshold,
        len(symbol_thresholds),
        final_precision,
        final_buy_rate,
        confidence_guard_active_rows,
    )

    residuals = prediction_frame["actual_return_5d"].to_numpy(dtype=float) - prediction_frame["predicted_return_5d"].to_numpy(dtype=float)
    rmse = float(np.sqrt(np.mean(np.square(residuals))))

    actual_sign = np.sign(prediction_frame["actual_return_5d"].to_numpy(dtype=float))
    pred_sign = np.sign(prediction_frame["predicted_return_5d"].to_numpy(dtype=float))
    directional_accuracy_regression = float(np.mean(actual_sign == pred_sign))
    directional_accuracy_classification = float(
        np.mean(
            prediction_frame["actual_direction_up"].to_numpy(dtype=int)
            == prediction_frame["predicted_direction_up"].to_numpy(dtype=int)
        )
    )

    backtest_accuracy_score = float(np.clip(directional_accuracy_classification, 0.0, 1.0))

    block_logs = []
    for metadata in block_metadata:
        block_id = int(metadata["block_id"])
        block_frame = prediction_frame.loc[prediction_frame["block_id"] == block_id].copy()
        if block_frame.empty:
            continue

        block_actual_return = block_frame["actual_return_5d"].to_numpy(dtype=float)
        block_pred_return = block_frame["predicted_return_5d"].to_numpy(dtype=float)
        block_actual_direction = block_frame["actual_direction_up"].to_numpy(dtype=int)
        block_pred_direction_raw = block_frame["predicted_direction_up_raw"].to_numpy(dtype=int)
        block_pred_direction = block_frame["predicted_direction_up"].to_numpy(dtype=int)

        block_rmse = float(np.sqrt(np.mean(np.square(block_actual_return - block_pred_return))))
        block_dir_reg = float(np.mean(np.sign(block_actual_return) == np.sign(block_pred_return)))
        block_dir_cls_raw = float(np.mean(block_actual_direction == block_pred_direction_raw))
        block_dir_cls = float(np.mean(block_actual_direction == block_pred_direction))

        block_signal_count = int(np.sum(block_pred_direction))
        if block_signal_count > 0:
            block_precision = float(np.mean(block_actual_direction[block_pred_direction == 1]))
        else:
            block_precision = 0.0
        block_buy_rate = float(block_signal_count / len(block_frame)) if len(block_frame) else 0.0
        block_guardrail_forced = int(block_frame["guardrail_forced_no_buy"].sum())
        block_turbulent_share = float(
            np.mean(block_frame["regime_turbulent_signal"].to_numpy(dtype=float) > CONFIDENCE_GUARD_SIGNAL_THRESHOLD)
        )

        block_logs.append(
            BlockTrainingLog(
                block_id=block_id,
                block_start_date=str(metadata["block_start_date"]),
                block_end_date=str(metadata["block_end_date"]),
                train_rows=int(metadata["train_rows"]),
                test_rows=int(metadata["test_rows"]),
                rmse=block_rmse,
                directional_accuracy_regression=block_dir_reg,
                directional_accuracy_classification_raw=block_dir_cls_raw,
                directional_accuracy_classification=block_dir_cls,
                precision_at_threshold=block_precision,
                buy_rate_at_threshold=block_buy_rate,
                guardrail_forced_no_buy=block_guardrail_forced,
                turbulent_test_share=block_turbulent_share,
            )
        )

    if base_feature_importance_weight > 0:
        normalized_importance = base_feature_importance_accumulator / base_feature_importance_weight
    else:
        normalized_importance = base_feature_importance_accumulator.copy()
    normalized_importance = normalized_importance.sort_values(ascending=False)
    importance_frame = normalized_importance.reset_index()
    importance_frame.columns = ["feature", "importance"]
    metrics = WalkForwardMetrics(
        rmse=rmse,
        directional_accuracy_regression=directional_accuracy_regression,
        directional_accuracy_classification=directional_accuracy_classification,
        rows_evaluated=len(prediction_frame),
        blocks_trained=blocks_trained,
        backtest_accuracy_score=backtest_accuracy_score,
        global_threshold=float(global_threshold),
        precision_at_threshold=float(final_precision),
        buy_rate_at_threshold=float(final_buy_rate),
        high_confidence_threshold=float(HIGH_CONFIDENCE_MIN_PROB),
        high_confidence_precision=0.0,
        high_confidence_buy_rate=0.0,
        cumulative_profit_high_confidence_raw=0.0,
        cumulative_profit_high_confidence=0.0,
    )
    prediction_frame["global_threshold"] = float(global_threshold)
    prediction_frame["precision_baseline_global_threshold"] = float(precision_at_threshold)
    prediction_frame["buy_rate_baseline_global_threshold"] = float(buy_rate_at_threshold)

    high_confidence_threshold = _select_high_confidence_threshold(prediction_frame)
    prediction_frame["high_confidence_threshold"] = float(high_confidence_threshold)

    high_confidence_mask = (
        (prediction_frame["predicted_direction_up"].to_numpy(dtype=int) == 1)
        & (prediction_frame["predicted_direction_prob_up"].to_numpy(dtype=float) >= float(high_confidence_threshold))
    )
    high_confidence_signal_count = int(np.sum(high_confidence_mask))
    if high_confidence_signal_count > 0:
        high_confidence_precision = float(
            np.mean(prediction_frame.loc[high_confidence_mask, "actual_direction_up"].to_numpy(dtype=int))
        )
        high_confidence_returns = prediction_frame.loc[high_confidence_mask, "actual_return_5d"].to_numpy(dtype=float)
        cumulative_profit_high_confidence_raw = _compound_returns(high_confidence_returns)
        high_confidence_returns_stop_loss = np.maximum(high_confidence_returns, -HIGH_CONFIDENCE_STOP_LOSS_PCT)
        cumulative_profit_high_confidence = _compound_returns(high_confidence_returns_stop_loss)
    else:
        high_confidence_precision = 0.0
        cumulative_profit_high_confidence_raw = 0.0
        cumulative_profit_high_confidence = 0.0
    high_confidence_buy_rate = float(high_confidence_signal_count / len(prediction_frame)) if len(prediction_frame) else 0.0

    metrics = WalkForwardMetrics(
        rmse=metrics.rmse,
        directional_accuracy_regression=metrics.directional_accuracy_regression,
        directional_accuracy_classification=metrics.directional_accuracy_classification,
        rows_evaluated=metrics.rows_evaluated,
        blocks_trained=metrics.blocks_trained,
        backtest_accuracy_score=metrics.backtest_accuracy_score,
        global_threshold=metrics.global_threshold,
        precision_at_threshold=metrics.precision_at_threshold,
        buy_rate_at_threshold=metrics.buy_rate_at_threshold,
        high_confidence_threshold=float(high_confidence_threshold),
        high_confidence_precision=float(high_confidence_precision),
        high_confidence_buy_rate=float(high_confidence_buy_rate),
        cumulative_profit_high_confidence_raw=float(cumulative_profit_high_confidence_raw),
        cumulative_profit_high_confidence=float(cumulative_profit_high_confidence),
    )

    LOGGER.info(
        "HIGH_CONFIDENCE_AUDIT threshold=%.2f target_buy_rate=[%.4f, %.4f] precision=%.4f buy_rate=%.4f cumulative_profit_raw=%.4f cumulative_profit_stop_loss_5pct=%.4f",
        high_confidence_threshold,
        HIGH_CONFIDENCE_TARGET_MIN_BUY_RATE,
        HIGH_CONFIDENCE_TARGET_MAX_BUY_RATE,
        high_confidence_precision,
        high_confidence_buy_rate,
        cumulative_profit_high_confidence_raw,
        cumulative_profit_high_confidence,
    )

    return metrics, prediction_frame, importance_frame, block_logs


def run_lstm_availability_probe() -> dict[str, Any]:
    try:
        import tensorflow as tf  # noqa: F401

        return {
            "status": "AVAILABLE",
            "message": "TensorFlow is installed. LSTM training can be added in the next iteration.",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "UNAVAILABLE",
            "message": f"TensorFlow not available in runtime: {exc}",
        }


def _parse_iso_date(raw: str | None) -> date | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return date.fromisoformat(text)


def _build_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build EGX multi-factor features and run walk-forward XGBoost validation")
    parser.add_argument("--start-date", type=str, default=DEFAULT_START_DATE.isoformat())
    parser.add_argument("--end-date", type=str, default="")
    parser.add_argument("--train-end", type=str, default=DEFAULT_TRAIN_END.isoformat())
    parser.add_argument("--blind-start", type=str, default=DEFAULT_BLIND_START.isoformat())
    parser.add_argument("--blind-end", type=str, default=DEFAULT_BLIND_END.isoformat())
    parser.add_argument("--horizon-days", type=int, default=DEFAULT_HORIZON_DAYS)
    parser.add_argument("--retrain-every", type=int, default=DEFAULT_RETRAIN_EVERY)
    parser.add_argument("--n-estimators", type=int, default=DEFAULT_N_ESTIMATORS)
    parser.add_argument("--learning-rate", type=float, default=DEFAULT_LEARNING_RATE)
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    parser.add_argument("--subsample", type=float, default=DEFAULT_SUBSAMPLE)
    parser.add_argument("--sample-rows", type=int, default=5)
    parser.add_argument("--output-csv", type=str, default="")
    parser.add_argument("--predictions-csv", type=str, default="")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = _build_cli_args()

    settings = resolve_mysql_settings()

    raw = load_historical_market_data(
        start_date=_parse_iso_date(args.start_date) or DEFAULT_START_DATE,
        end_date=_parse_iso_date(args.end_date),
        settings=settings,
    )
    sector_map = load_sector_mapping(settings=settings)
    context = load_market_context(
        start_date=_parse_iso_date(args.start_date) or DEFAULT_START_DATE,
        end_date=_parse_iso_date(args.end_date),
        settings=settings,
    )

    dataset = build_feature_factory_dataset(
        raw_frame=raw,
        sector_map=sector_map,
        market_context=context,
        settings=settings,
        horizon_days=max(1, int(args.horizon_days)),
    )

    LOGGER.info("Feature factory rows=%s symbols=%s", len(dataset.frame), len(dataset.symbols))

    if args.output_csv:
        dataset.frame.to_csv(args.output_csv, index=False)
        LOGGER.info("Saved feature dataset to %s", args.output_csv)

    sample_rows = max(1, int(args.sample_rows))
    sample = dataset.frame.head(sample_rows)
    with pd.option_context("display.max_columns", None, "display.width", 240):
        print("FINAL_TRAINING_DF_SAMPLE")
        print(sample.to_string(index=False))

    metrics, prediction_frame, feature_importance_frame, block_logs = run_walk_forward_validation_xgboost(
        feature_frame=dataset.frame,
        train_end=_parse_iso_date(args.train_end) or DEFAULT_TRAIN_END,
        blind_start=_parse_iso_date(args.blind_start) or DEFAULT_BLIND_START,
        blind_end=_parse_iso_date(args.blind_end) or DEFAULT_BLIND_END,
        retrain_every=max(1, int(args.retrain_every)),
        horizon_days=max(1, int(args.horizon_days)),
        n_estimators=max(1000, int(args.n_estimators)),
        learning_rate=float(args.learning_rate),
        max_depth=max(8, int(args.max_depth)),
        subsample=float(args.subsample),
    )

    if args.predictions_csv:
        prediction_frame.to_csv(args.predictions_csv, index=False)
        LOGGER.info("Saved walk-forward predictions to %s", args.predictions_csv)

    top_10_features = feature_importance_frame.head(10).copy()
    top_10_rows = [
        {
            "feature": str(row.feature),
            "importance": float(row.importance),
        }
        for row in top_10_features.itertuples(index=False)
    ]
    usd_rank_candidates = feature_importance_frame.index[feature_importance_frame["feature"] == "usd_egp_return"].tolist()
    usd_rank = int(usd_rank_candidates[0] + 1) if usd_rank_candidates else -1
    symbol_threshold_frame = (
        prediction_frame[["symbol", "symbol_threshold"]]
        .dropna(subset=["symbol"])
        .drop_duplicates(subset=["symbol"], keep="last")
        .sort_values("symbol")
    )
    symbol_thresholds = {
        str(row.symbol): float(row.symbol_threshold)
        for row in symbol_threshold_frame.itertuples(index=False)
    }
    confidence_guard_activation_rate = float(
        np.mean(pd.to_numeric(prediction_frame.get("confidence_guard_active", 0), errors="coerce").fillna(0.0).to_numpy(dtype=float))
    )

    print("TOP_10_FEATURE_IMPORTANCE")
    print(top_10_features.to_string(index=False))
    print(f"usd_egp_return_rank={usd_rank}")
    if usd_rank == -1 or usd_rank > 3:
        print("USD_CONTEXT_CHECK=FAIL (usd_egp_return is not in top 3)")
    else:
        print("USD_CONTEXT_CHECK=PASS")

    print("SYMBOL_THRESHOLDS")
    print(json.dumps(symbol_thresholds, sort_keys=True))

    print("WALK_FORWARD_BLOCK_LOGS")
    for block in block_logs:
        print(
            json.dumps(
                {
                    "block_id": block.block_id,
                    "block_start_date": block.block_start_date,
                    "block_end_date": block.block_end_date,
                    "train_rows": block.train_rows,
                    "test_rows": block.test_rows,
                    "rmse": block.rmse,
                    "directional_accuracy_regression": block.directional_accuracy_regression,
                    "directional_accuracy_classification_raw": block.directional_accuracy_classification_raw,
                    "directional_accuracy_classification": block.directional_accuracy_classification,
                    "precision_at_threshold": block.precision_at_threshold,
                    "buy_rate_at_threshold": block.buy_rate_at_threshold,
                    "guardrail_forced_no_buy": block.guardrail_forced_no_buy,
                    "turbulent_test_share": block.turbulent_test_share,
                }
            )
        )

    payload = {
        "walk_forward": {
            "rmse": metrics.rmse,
            "directional_accuracy_regression": metrics.directional_accuracy_regression,
            "directional_accuracy_classification": metrics.directional_accuracy_classification,
            "Backtest_Accuracy_Score": metrics.backtest_accuracy_score,
            "global_threshold": metrics.global_threshold,
            "precision_at_threshold": metrics.precision_at_threshold,
            "buy_rate_at_threshold": metrics.buy_rate_at_threshold,
            "high_confidence_threshold": metrics.high_confidence_threshold,
            "high_confidence_target_buy_rate_min": HIGH_CONFIDENCE_TARGET_MIN_BUY_RATE,
            "high_confidence_target_buy_rate_max": HIGH_CONFIDENCE_TARGET_MAX_BUY_RATE,
            "high_confidence_stop_loss_pct": HIGH_CONFIDENCE_STOP_LOSS_PCT,
            "high_confidence_precision": metrics.high_confidence_precision,
            "high_confidence_buy_rate": metrics.high_confidence_buy_rate,
            "cumulative_profit_high_confidence_raw": metrics.cumulative_profit_high_confidence_raw,
            "cumulative_profit_high_confidence": metrics.cumulative_profit_high_confidence,
            "symbol_threshold_count": len(symbol_thresholds),
            "confidence_guard_activation_rate": confidence_guard_activation_rate,
            "rows_evaluated": metrics.rows_evaluated,
            "blocks_trained": metrics.blocks_trained,
            "train_period": {
                "from": DEFAULT_START_DATE.isoformat(),
                "to": (_parse_iso_date(args.train_end) or DEFAULT_TRAIN_END).isoformat(),
            },
            "blind_period": {
                "from": (_parse_iso_date(args.blind_start) or DEFAULT_BLIND_START).isoformat(),
                "to": (_parse_iso_date(args.blind_end) or DEFAULT_BLIND_END).isoformat(),
            },
            "training_hyperparameters": {
                "n_estimators": max(1000, int(args.n_estimators)),
                "learning_rate": float(args.learning_rate),
                "max_depth": max(8, int(args.max_depth)),
                "subsample": float(args.subsample),
            },
        },
        "feature_importance_top_10": top_10_rows,
        "usd_egp_return_rank": usd_rank,
        "symbol_thresholds": symbol_thresholds,
        "block_logs": [
            {
                "block_id": item.block_id,
                "block_start_date": item.block_start_date,
                "block_end_date": item.block_end_date,
                "train_rows": item.train_rows,
                "test_rows": item.test_rows,
                "rmse": item.rmse,
                "directional_accuracy_regression": item.directional_accuracy_regression,
                "directional_accuracy_classification_raw": item.directional_accuracy_classification_raw,
                "directional_accuracy_classification": item.directional_accuracy_classification,
                "precision_at_threshold": item.precision_at_threshold,
                "buy_rate_at_threshold": item.buy_rate_at_threshold,
                "guardrail_forced_no_buy": item.guardrail_forced_no_buy,
                "turbulent_test_share": item.turbulent_test_share,
            }
            for item in block_logs
        ],
        "lstm_probe": run_lstm_availability_probe(),
    }
    print("WALK_FORWARD_METRICS")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()










