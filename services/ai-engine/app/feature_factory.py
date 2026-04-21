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
MACRO_DIRECTION_BLEND_WEIGHT = 0.35
REGIME_TURBULENT_QUANTILE = 0.8
REGIME_SIMILARITY_WEIGHT_MULTIPLIER = 3.0
REGIME_STABLE_BLEND_WEIGHT = 0.25
REGIME_TURBULENT_BLEND_WEIGHT = 0.75
HIGH_ERROR_SYMBOL_ROOTS = {"GDWA", "OBRI", "AUTO"}

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
    "cbe_policy_rate_pct",
    "cbe_rate_changed",
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

    crisis_rows_weighted = np.zeros(len(train_slice), dtype=bool)
    if current_regime_score >= turbulent_threshold and len(local_score) > 0:
        distance = (local_score - current_regime_score).abs()
        similarity_band = float(distance.quantile(0.35)) if len(distance) else 0.0
        if similarity_band <= 1e-8:
            similarity_band = max(float(local_score.std()), 0.05)

        crisis_rows_weighted = (
            (local_score >= (0.9 * turbulent_threshold))
            & (distance <= similarity_band)
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
) -> tuple[float, float, float]:
    if len(y_true) == 0:
        return 0.5, 0.0, 0.0

    min_signals = max(20, int(0.01 * len(y_true)))
    best_threshold = 0.5
    best_precision = -1.0
    best_buy_rate = 0.0

    for threshold in np.linspace(0.50, 0.90, 17):
        predicted = (prob_up >= float(threshold)).astype(int)
        signal_count = int(np.sum(predicted))
        if signal_count < min_signals:
            continue

        positives = y_true[predicted == 1]
        precision = float(np.mean(positives)) if len(positives) else 0.0
        buy_rate = float(signal_count / len(y_true))

        if precision > (best_precision + 1e-12):
            best_precision = precision
            best_threshold = float(threshold)
            best_buy_rate = buy_rate
            continue

        if np.isclose(precision, best_precision) and buy_rate > best_buy_rate:
            best_threshold = float(threshold)
            best_buy_rate = buy_rate

    if best_precision < 0.0:
        fallback_predicted = (prob_up >= 0.5).astype(int)
        fallback_signal_count = int(np.sum(fallback_predicted))
        if fallback_signal_count == 0:
            return 0.5, 0.0, 0.0

        fallback_precision = float(np.mean(y_true[fallback_predicted == 1]))
        fallback_buy_rate = float(fallback_signal_count / len(y_true))
        return 0.5, fallback_precision, fallback_buy_rate

    return best_threshold, best_precision, best_buy_rate


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

    def _enrich(group: pd.DataFrame) -> pd.DataFrame:
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

        return local

    return ordered.groupby("symbol", group_keys=False).apply(_enrich).reset_index(drop=True)


def build_feature_factory_dataset(
    raw_frame: pd.DataFrame,
    sector_map: dict[str, str],
    market_context: pd.DataFrame,
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

    merged[["usd_egp_close", "gold_usd_close", "cbe_policy_rate_pct", "usd_egp_return", "gold_return"]] = merged[
        ["usd_egp_close", "gold_usd_close", "cbe_policy_rate_pct", "usd_egp_return", "gold_return"]
    ].ffill().bfill()
    merged["cbe_rate_changed"] = merged["cbe_rate_changed"].fillna(0).astype(int)

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


def _build_model_matrix(frame: pd.DataFrame, expected_columns: list[str] | None = None) -> pd.DataFrame:
    local = frame.copy()
    local["symbol"] = local["symbol"].astype(str).str.upper()
    local["sector_code"] = local["sector_code"].astype(str).str.upper()

    model_frame = local[FEATURE_COLUMNS + ["symbol", "sector_code"]]
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
            sample_weight=stable_weights,
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            max_depth=max(6, int(max_depth) - 1),
            subsample=min(1.0, float(subsample) + 0.05),
        )
        if stable_direction_model is None:
            stable_direction_model = _fit_direction_classifier(
                x_train=x_train,
                y_train_binary=y_train_direction,
                sample_weight=np.clip(train_sample_weights, 1.0, 18.0),
                n_estimators=n_estimators,
                learning_rate=learning_rate,
                max_depth=max_depth,
                subsample=subsample,
            )

        turbulent_direction_model = _fit_direction_classifier(
            x_train=x_train.loc[turbulent_mask],
            y_train_binary=y_train_direction[turbulent_mask],
            sample_weight=turbulent_weights,
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
        regime_turbulent_signal = (
            (regime_blend_weight >= 0.5)
            | row_turbulent_mask.astype(bool)
            | yesterday_turbulent_mask.astype(bool)
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
        aligned_base_importance = _apply_macro_importance_prior(aligned_base_importance)
        weight = float(len(train_slice))
        base_feature_importance_accumulator = base_feature_importance_accumulator.add(aligned_base_importance * weight)
        base_feature_importance_weight += weight

        LOGGER.info(
            "WF_BLOCK %02d/%02d DONE: rmse=%.6f dir_acc_reg=%.4f dir_acc_cls_raw=%.4f turbulent_test_share=%.4f crisis_rows_weighted=%s current_regime_score=%.4f",
            block_id,
            total_blocks,
            block_rmse,
            block_reg_direction,
            block_clf_direction_raw,
            float(np.mean(regime_turbulent_signal.astype(float))),
            crisis_rows_weighted,
            current_regime_score,
        )

        batch = test_slice[["trade_date", "symbol", "sector_code", "close_price", "ema_200"]].copy()
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
        batch["regime_blend_weight"] = regime_blend_weight
        batch["regime_turbulent_signal"] = regime_turbulent_signal.astype(int)
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

    print("TOP_10_FEATURE_IMPORTANCE")
    print(top_10_features.to_string(index=False))
    print(f"usd_egp_return_rank={usd_rank}")
    if usd_rank == -1 or usd_rank > 3:
        print("USD_CONTEXT_CHECK=FAIL (usd_egp_return is not in top 3)")
    else:
        print("USD_CONTEXT_CHECK=PASS")

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
                    "directional_accuracy_classification": block.directional_accuracy_classification,
                }
            )
        )

    payload = {
        "walk_forward": {
            "rmse": metrics.rmse,
            "directional_accuracy_regression": metrics.directional_accuracy_regression,
            "directional_accuracy_classification": metrics.directional_accuracy_classification,
            "Backtest_Accuracy_Score": metrics.backtest_accuracy_score,
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
        "block_logs": [
            {
                "block_id": item.block_id,
                "block_start_date": item.block_start_date,
                "block_end_date": item.block_end_date,
                "train_rows": item.train_rows,
                "test_rows": item.test_rows,
                "rmse": item.rmse,
                "directional_accuracy_regression": item.directional_accuracy_regression,
                "directional_accuracy_classification": item.directional_accuracy_classification,
            }
            for item in block_logs
        ],
        "lstm_probe": run_lstm_availability_probe(),
    }
    print("WALK_FORWARD_METRICS")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
