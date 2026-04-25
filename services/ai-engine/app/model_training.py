from __future__ import annotations

import argparse
import json
import logging
import os
import pickle
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
import sklearn
from sklearn.model_selection import StratifiedKFold, RandomizedSearchCV
from sklearn.metrics import accuracy_score, f1_score, classification_report
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import DMatrix, XGBRegressor, XGBClassifier

from .feature_engineering import (
    FEATURE_COLUMNS,
    build_feature_dataset,
    build_latest_feature_rows,
    load_historical_market_data,
)

LOGGER = logging.getLogger(__name__)

TargetMode = Literal["RETURN_PCT", "CLOSE_PRICE", "CLASSIFICATION"]

DEFAULT_MODEL_DIR = Path("/app/models")
DEFAULT_HORIZON_DAYS = 5
DEFAULT_MIN_ROWS_PER_SYMBOL = 120
DEFAULT_TARGET_MODE: TargetMode = "CLASSIFICATION"  # Switched to classification for high-precision
DEFAULT_TRAIN_START = date(2016, 1, 1)
DEFAULT_TRAIN_END = date(2026, 4, 20)
DEFAULT_VALIDATION_START = date(2026, 4, 21)
DEFAULT_VALIDATION_END = date(2026, 12, 31)
RECENCY_WEIGHT_START = date(2023, 1, 1)
MANIFEST_FILE_NAME = "model_manifest.json"

_MODEL_CACHE_LOCK = threading.Lock()
_MODEL_CACHE: dict[str, Any] = {
    "modelDir": None,
    "manifestMtime": None,
    "manifest": {},
    "models": {},
}


@dataclass(frozen=True)
class SymbolForecast:
    symbol: str
    predicted_price_5d: float
    predicted_return_5d: float
    confidence_score: float
    model_accuracy: float
    relative_volume_60d: float
    market_sentiment_score: float
    smart_money_signal: float
    global_factor_corr_sp500: float
    alt_news_sentiment_score: float
    alt_urea_price: float
    alt_brent_price: float
    alt_news_influence_share: float
    alt_urea_influence_share: float
    alt_brent_influence_share: float
    predicted_class: int = 1  # 0=SELL, 1=HOLD, 2=BUY (for classification mode)
    action: str = "HOLD"  # BUY, HOLD, SELL, PREVENTIVE_SELL (derived from predicted_class)


@dataclass(frozen=True)
class ForecastBatch:
    forecasts: dict[str, SymbolForecast]
    warnings: list[str]
    model_accuracy: float


def normalize_target_mode(raw_mode: str | None) -> TargetMode:
    normalized = (raw_mode or DEFAULT_TARGET_MODE).strip().upper()
    if normalized in {"RETURN", "RETURN_PCT", "RETURNS", "RETURN_PERCENT"}:
        return "RETURN_PCT"
    if normalized in {"CLOSE", "CLOSE_PRICE", "PRICE"}:
        return "CLOSE_PRICE"
    return DEFAULT_TARGET_MODE


def _target_column(target_mode: TargetMode) -> str:
    if target_mode == "CLASSIFICATION":
        return "target_class_5d"
    return "target_return_5d" if target_mode == "RETURN_PCT" else "target_close_5d"


def _get_optimized_xgboost_params(
    x_train: pd.DataFrame,
    y_train: pd.Series,
    sample_weight: np.ndarray | None,
    n_iter: int = 8,
    cv_folds: int = 3,
) -> dict[str, Any]:
    """
    Lightweight Hyperparameter Optimization per stock.
    Tunes max_depth and learning_rate to find optimal values.
    Keeps iterations low (n_iter=8) to avoid massive training times.
    """
    param_distributions = {
        "max_depth": [3, 5, 7],
        "learning_rate": [0.01, 0.05, 0.1],
    }

    # Use fewer estimators for HPO to keep it fast
    base_model = XGBClassifier(
        objective="multi:softprob",
        num_class=3,
        eval_metric='mlogloss',
        n_estimators=200,  # Fewer trees for HPO speed
        min_child_weight=2,
        subsample=0.90,
        colsample_bytree=0.90,
        reg_lambda=1.0,
        random_state=42,
        n_jobs=2,
    )

    try:
        search = RandomizedSearchCV(
            estimator=base_model,
            param_distributions=param_distributions,
            n_iter=n_iter,
            scoring='f1_macro',
            cv=cv_folds,
            random_state=42,
            n_jobs=1,  # Keep n_jobs=1 to avoid nested parallelism issues
            verbose=0,
        )

        search.fit(x_train, y_train, sample_weight=sample_weight)
        best_params = search.best_params_

        LOGGER.debug(
            "HPO complete: best_max_depth=%s best_learning_rate=%s best_score=%.4f",
            best_params.get("max_depth"),
            best_params.get("learning_rate"),
            search.best_score_,
        )

        return {
            "max_depth": best_params.get("max_depth", 5),
            "learning_rate": best_params.get("learning_rate", 0.07),
        }
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("HPO failed, using defaults: %s", exc)
        return {"max_depth": 5, "learning_rate": 0.07}


def _compute_classification_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """Compute classification accuracy and F1-scores for multi-class."""
    if y_true.size == 0:
        return {"accuracy": 0.0, "f1_macro": 0.0, "f1_buy": 0.0, "f1_hold": 0.0, "f1_sell": 0.0}

    # Ensure predictions are integers
    y_pred_int = np.round(y_pred).astype(int)
    y_pred_int = np.clip(y_pred_int, 0, 2)  # Clip to valid class range [0, 1, 2]

    accuracy = float(accuracy_score(y_true, y_pred_int))
    f1_macro = float(f1_score(y_true, y_pred_int, average="macro", zero_division=0))

    # Per-class F1 scores
    f1_per_class = f1_score(y_true, y_pred_int, average=None, labels=[0, 1, 2], zero_division=0)

    return {
        "accuracy": accuracy,
        "f1_macro": f1_macro,
        "f1_buy": float(f1_per_class[2]),    # Class 2 = BUY
        "f1_hold": float(f1_per_class[1]),   # Class 1 = HOLD
        "f1_sell": float(f1_per_class[0]),   # Class 0 = SELL
    }


def _resolve_model_dir(model_dir: str | Path | None) -> Path:
    if model_dir is None:
        configured = os.getenv("AI_MODEL_DIR", str(DEFAULT_MODEL_DIR)).strip()
        return Path(configured)
    return Path(model_dir)


def _model_path_for_symbol(model_dir: Path, symbol: str, target_mode: TargetMode) -> Path:
    token = symbol.upper().replace("/", "_").replace("\\", "_")
    return model_dir / f"{token}_{target_mode.lower()}_xgb.pkl"


def _manifest_path(model_dir: Path) -> Path:
    return model_dir / MANIFEST_FILE_NAME


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return float(fallback)


def _mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if y_true.size == 0:
        return 0.0
    return float(np.mean(np.abs(y_true - y_pred)))


def _mse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if y_true.size == 0:
        return 0.0
    errors = y_true - y_pred
    return float(np.mean(errors * errors))


def _r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if y_true.size == 0:
        return 0.0

    y_mean = float(np.mean(y_true))
    ss_tot = float(np.sum((y_true - y_mean) ** 2))
    if ss_tot <= 1e-12:
        return 0.0

    ss_res = float(np.sum((y_true - y_pred) ** 2))
    return float(1.0 - (ss_res / ss_tot))


def _compute_accuracy_score(y_true: np.ndarray, y_pred: np.ndarray, target_mode: TargetMode) -> float:
    if y_true.size == 0:
        return 0.0

    if target_mode == "RETURN_PCT":
        direction = np.mean(np.sign(y_true) == np.sign(y_pred))
        denominator = np.maximum(np.abs(y_true), 1e-6)
        mape = np.mean(np.abs((y_true - y_pred) / denominator))
        error_score = max(0.0, 1.0 - float(mape))
        return float(np.clip((0.60 * direction) + (0.40 * error_score), 0.0, 1.0))

    denominator = np.maximum(np.abs(y_true), 1e-6)
    mape = np.mean(np.abs((y_true - y_pred) / denominator))
    return float(np.clip(1.0 - float(mape), 0.0, 1.0))


def _build_recency_sample_weights(trade_dates: pd.Series) -> np.ndarray:
    """
    Build sample weights with aggressive recency weighting.
    2025-2026 data gets 3x weight to emphasize volatile recent patterns.
    """
    dates = pd.to_datetime(trade_dates, errors="coerce")
    weights = np.ones(len(dates), dtype=float)

    # Base recency weighting from 2023 onwards
    recent_mask = dates >= pd.Timestamp(RECENCY_WEIGHT_START)
    weights[recent_mask] = 1.5

    # 2025 data gets 2.5x weight
    weights[dates >= pd.Timestamp(date(2025, 1, 1))] = 2.5

    # 2026 data gets 3x weight (highest priority - current economic reality)
    weights[dates >= pd.Timestamp(date(2026, 1, 1))] = 3.0

    return weights


def _estimate_tree_uncertainty_std(model: XGBRegressor, x_row: pd.DataFrame) -> float:
    try:
        booster = model.get_booster()
        rounds = int(booster.num_boosted_rounds())
        if rounds <= 1:
            return 0.0

        dmatrix = DMatrix(x_row)
        per_tree_margins: list[float] = []
        for idx in range(rounds):
            margin = booster.predict(
                dmatrix,
                output_margin=True,
                iteration_range=(idx, idx + 1),
            )
            if margin.size:
                per_tree_margins.append(float(margin[0]))

        if len(per_tree_margins) < 2:
            return 0.0

        return float(np.std(np.array(per_tree_margins, dtype=float)))
    except Exception:  # noqa: BLE001
        return 0.0


def _compute_local_feature_influence_shares(
    model: XGBRegressor,
    x_row: pd.DataFrame,
    feature_columns: list[str],
) -> dict[str, float]:
    try:
        importance = getattr(model, "feature_importances_", None)
        if importance is None:
            return {
                "alt_news_influence_share": 0.0,
                "alt_urea_influence_share": 0.0,
                "alt_brent_influence_share": 0.0,
            }

        importance_series = pd.Series(np.asarray(importance, dtype=float), index=feature_columns, dtype=float)
        row = x_row.iloc[0]
        contribution = (row.abs() * importance_series).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        total = float(contribution.sum())
        if total <= 1e-12:
            return {
                "alt_news_influence_share": 0.0,
                "alt_urea_influence_share": 0.0,
                "alt_brent_influence_share": 0.0,
            }

        return {
            "alt_news_influence_share": float(contribution.get("alt_news_sentiment_score", 0.0) / total),
            "alt_urea_influence_share": float(contribution.get("alt_urea_price", 0.0) / total),
            "alt_brent_influence_share": float(contribution.get("alt_brent_price", 0.0) / total),
        }
    except Exception:  # noqa: BLE001
        return {
            "alt_news_influence_share": 0.0,
            "alt_urea_influence_share": 0.0,
            "alt_brent_influence_share": 0.0,
        }


def train_xgboost_models(
    model_dir: str | Path | None = None,
    target_mode: str | None = None,
    symbols: list[str] | None = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    min_rows_per_symbol: int = DEFAULT_MIN_ROWS_PER_SYMBOL,
    train_start: date = DEFAULT_TRAIN_START,
    train_end: date = DEFAULT_TRAIN_END,
    validation_start: date = DEFAULT_VALIDATION_START,
    validation_end: date = DEFAULT_VALIDATION_END,
    use_recency_weighting: bool = True,
    n_estimators: int = 380,
    learning_rate: float = 0.07,
) -> dict[str, Any]:
    resolved_n_estimators = max(100, int(n_estimators))
    resolved_learning_rate = max(0.01, min(0.3, float(learning_rate)))
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1")

    resolved_target_mode = normalize_target_mode(target_mode)
    target_column = _target_column(resolved_target_mode)

    model_root = _resolve_model_dir(model_dir)
    model_root.mkdir(parents=True, exist_ok=True)

    raw = load_historical_market_data(
        symbols=symbols,
        start_date=train_start,
        end_date=validation_end,
    )
    features = build_feature_dataset(raw, horizon_days=horizon_days).frame

    if features.empty:
        raise RuntimeError("No rows available for model training")

    features = features.sort_values(["symbol", "trade_date"]).reset_index(drop=True)

    symbol_metrics: dict[str, dict[str, Any]] = {}
    trained_models = 0
    skipped_symbols: dict[str, str] = {}

    for symbol, group in features.groupby("symbol"):
        ordered = group.sort_values("trade_date").copy()
        train_mask = (ordered["trade_date"] >= pd.Timestamp(train_start)) & (ordered["trade_date"] <= pd.Timestamp(train_end))
        val_mask = (ordered["trade_date"] >= pd.Timestamp(validation_start)) & (ordered["trade_date"] <= pd.Timestamp(validation_end))

        train_rows = int(train_mask.sum())
        validation_rows = int(val_mask.sum())

        if train_rows < min_rows_per_symbol:
            skipped_symbols[symbol] = f"Insufficient training rows: {train_rows}"
            continue

        if validation_rows < max(20, int(min_rows_per_symbol * 0.15)):
            skipped_symbols[symbol] = f"Insufficient validation rows: {validation_rows}"
            continue

        x_train = ordered.loc[train_mask, FEATURE_COLUMNS].astype(float)
        y_train = ordered.loc[train_mask, target_column].astype(float)
        train_dates = ordered.loc[train_mask, "trade_date"]

        x_val = ordered.loc[val_mask, FEATURE_COLUMNS].astype(float)
        y_val = ordered.loc[val_mask, target_column].astype(float)

        train_sample_weight = _build_recency_sample_weights(train_dates) if use_recency_weighting else None

        # Classification Mode: Use XGBClassifier with StratifiedKFold
        if resolved_target_mode == "CLASSIFICATION":
            # Convert targets to integers for classification
            y_train_int = y_train.round().astype(int).clip(0, 2)
            y_val_int = y_val.round().astype(int).clip(0, 2)

            # Compute balanced sample weights to fix class imbalance
            # This forces the model to treat BUY signals with equal importance to SELL signals
            balanced_sample_weights = compute_sample_weight('balanced', y_train_int)

            # Combine with recency weights if enabled
            if use_recency_weighting:
                recency_weights = _build_recency_sample_weights(train_dates)
                # Multiply balanced weights by recency weights
                combined_weights = balanced_sample_weights * recency_weights
            else:
                combined_weights = balanced_sample_weights

            # Lightweight HPO: Find optimal max_depth and learning_rate per stock
            # Use balanced weights for HPO to ensure fair class representation
            hpo_weights = compute_sample_weight('balanced', y_train_int)
            if use_recency_weighting:
                hpo_weights = hpo_weights * _build_recency_sample_weights(train_dates)

            optimized_params = _get_optimized_xgboost_params(
                x_train, y_train_int, sample_weight=hpo_weights, n_iter=8, cv_folds=3
            )
            best_max_depth = int(optimized_params["max_depth"])
            best_learning_rate = float(optimized_params["learning_rate"])

            LOGGER.info(
                "Symbol=%s HPO results: max_depth=%s learning_rate=%s",
                symbol, best_max_depth, best_learning_rate,
            )

            # Use StratifiedKFold for cross-validation with optimized params
            skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
            cv_scores = []

            for fold, (train_idx, val_idx) in enumerate(skf.split(x_train, y_train_int)):
                x_fold_train, x_fold_val = x_train.iloc[train_idx], x_train.iloc[val_idx]
                y_fold_train, y_fold_val = y_train_int.iloc[train_idx], y_train_int.iloc[val_idx]

                fold_model = XGBClassifier(
                    objective="multi:softprob",
                    num_class=3,
                    eval_metric='mlogloss',
                    n_estimators=max(50, resolved_n_estimators // 3),
                    learning_rate=best_learning_rate,
                    max_depth=best_max_depth,
                    min_child_weight=2,
                    subsample=0.90,
                    colsample_bytree=0.90,
                    reg_lambda=1.0,
                    random_state=42 + fold,
                    n_jobs=2,
                )

                fold_sample_weight = None
                if use_recency_weighting:
                    fold_dates = train_dates.iloc[train_idx]
                    fold_sample_weight = _build_recency_sample_weights(fold_dates)

                # Compute balanced weights for this fold
                fold_balanced_weights = compute_sample_weight('balanced', y_fold_train)
                if use_recency_weighting:
                    fold_recency_weights = _build_recency_sample_weights(train_dates.iloc[train_idx])
                    fold_combined_weights = fold_balanced_weights * fold_recency_weights
                else:
                    fold_combined_weights = fold_balanced_weights

                fold_model.fit(x_fold_train, y_fold_train, sample_weight=fold_combined_weights)
                fold_pred = fold_model.predict(x_fold_val)
                fold_acc = sklearn.metrics.accuracy_score(y_fold_val, fold_pred)
                cv_scores.append(fold_acc)

            # Final model on full training data with optimized hyperparameters
            model = XGBClassifier(
                objective="multi:softprob",
                num_class=3,
                eval_metric='mlogloss',
                n_estimators=resolved_n_estimators,
                learning_rate=best_learning_rate,
                max_depth=best_max_depth,
                min_child_weight=2,
                subsample=0.90,
                colsample_bytree=0.90,
                reg_lambda=1.0,
                random_state=42,
                n_jobs=2,
            )
            model.fit(x_train, y_train_int, sample_weight=combined_weights)

            # Validation predictions - get probabilities and predicted classes
            y_pred_proba = model.predict_proba(x_val)
            y_pred = np.argmax(y_pred_proba, axis=1)

            # Compute classification metrics
            class_metrics = _compute_classification_metrics(y_val_int.to_numpy(), y_pred)

            rmse = 0.0  # Not applicable for classification
            mae = 0.0   # Not applicable for classification
            r2 = 0.0    # Not applicable for classification
            accuracy_score_val = class_metrics["accuracy"]

        else:
            # Regression Mode (original logic)
            model = XGBRegressor(
                objective="reg:squarederror",
                n_estimators=resolved_n_estimators,
                learning_rate=resolved_learning_rate,
                max_depth=4,
                min_child_weight=2,
                subsample=0.90,
                colsample_bytree=0.90,
                reg_lambda=1.0,
                random_state=42,
                n_jobs=2,
            )
            model.fit(x_train, y_train, sample_weight=train_sample_weight)

            y_true = y_val.to_numpy(dtype=float)
            y_pred = model.predict(x_val).astype(float)

            rmse = float(np.sqrt(_mse(y_true, y_pred)))
            mae = _mae(y_true, y_pred)
            r2 = _r2(y_true, y_pred)
            accuracy_score_val = _compute_accuracy_score(y_true, y_pred, resolved_target_mode)
            class_metrics = None

        fit_mask = (ordered["trade_date"] >= pd.Timestamp(train_start)) & (ordered["trade_date"] <= pd.Timestamp(validation_end))
        fit_slice = ordered.loc[fit_mask].copy()
        x_fit = fit_slice[FEATURE_COLUMNS].astype(float)
        y_fit = fit_slice[target_column].astype(float)
        fit_sample_weight = (
            _build_recency_sample_weights(fit_slice["trade_date"])
            if use_recency_weighting
            else None
        )

        # Final model training - Classification vs Regression
        if resolved_target_mode == "CLASSIFICATION":
            y_fit_int = y_fit.round().astype(int).clip(0, 2)
            # Re-run lightweight HPO on full fit data for final model
            fit_hpo_weights = compute_sample_weight('balanced', y_fit_int)
            if use_recency_weighting:
                fit_hpo_weights = fit_hpo_weights * _build_recency_sample_weights(fit_slice["trade_date"])

            final_optimized_params = _get_optimized_xgboost_params(
                x_fit, y_fit_int, sample_weight=fit_hpo_weights, n_iter=6, cv_folds=3
            )
            final_max_depth = int(final_optimized_params["max_depth"])
            final_learning_rate = float(final_optimized_params["learning_rate"])

            final_model = XGBClassifier(
                objective="multi:softprob",
                num_class=3,
                eval_metric='mlogloss',
                n_estimators=resolved_n_estimators,
                learning_rate=final_learning_rate,
                max_depth=final_max_depth,
                min_child_weight=2,
                subsample=0.90,
                colsample_bytree=0.90,
                reg_lambda=1.0,
                random_state=42,
                n_jobs=2,
            )
            final_model.fit(x_fit, y_fit_int, sample_weight=fit_sample_weight)

            # Build metrics dict for classification
            metrics_dict = {
                "accuracyScore": accuracy_score_val,
                "accuracy": class_metrics["accuracy"] if class_metrics else accuracy_score_val,
                "f1Macro": class_metrics["f1_macro"] if class_metrics else 0.0,
                "f1Buy": class_metrics["f1_buy"] if class_metrics else 0.0,
                "f1Hold": class_metrics["f1_hold"] if class_metrics else 0.0,
                "f1Sell": class_metrics["f1_sell"] if class_metrics else 0.0,
                "trainRows": train_rows,
                "validationRows": validation_rows,
                "fitRows": int(len(fit_slice)),
            }
        else:
            final_model = XGBRegressor(
                objective="reg:squarederror",
                n_estimators=resolved_n_estimators,
                learning_rate=resolved_learning_rate,
                max_depth=4,
                min_child_weight=2,
                subsample=0.90,
                colsample_bytree=0.90,
                reg_lambda=1.0,
                random_state=42,
                n_jobs=2,
            )
            final_model.fit(x_fit, y_fit, sample_weight=fit_sample_weight)

            metrics_dict = {
                "rmse": rmse,
                "mae": mae,
                "r2": r2,
                "accuracyScore": accuracy_score,
                "trainRows": train_rows,
                "validationRows": validation_rows,
                "fitRows": int(len(fit_slice)),
            }

        payload = {
            "symbol": symbol,
            "targetMode": resolved_target_mode,
            "horizonDays": horizon_days,
            "featureColumns": FEATURE_COLUMNS,
            "trainedAtUtc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "metrics": metrics_dict,
            "model": final_model,
        }

        model_path = _model_path_for_symbol(model_root, symbol, resolved_target_mode)
        with model_path.open("wb") as model_file:
            pickle.dump(payload, model_file)
        trained_models += 1

        symbol_metrics[symbol] = {
            "modelPath": str(model_path),
            **metrics_dict,
        }

    if trained_models == 0:
        raise RuntimeError(f"No models trained. Skipped={skipped_symbols}")

    mean_accuracy = float(
        np.mean([_safe_float(item.get("accuracyScore"), 0.0) for item in symbol_metrics.values()])
    )

    # Calculate mean F1 scores for classification mode
    if resolved_target_mode == "CLASSIFICATION":
        mean_f1_macro = float(np.mean([_safe_float(item.get("f1Macro"), 0.0) for item in symbol_metrics.values()]))
        mean_f1_buy = float(np.mean([_safe_float(item.get("f1Buy"), 0.0) for item in symbol_metrics.values()]))
        mean_f1_hold = float(np.mean([_safe_float(item.get("f1Hold"), 0.0) for item in symbol_metrics.values()]))
        mean_f1_sell = float(np.mean([_safe_float(item.get("f1Sell"), 0.0) for item in symbol_metrics.values()]))
        model_type = "xgboost-classifier"
    else:
        mean_f1_macro = mean_f1_buy = mean_f1_hold = mean_f1_sell = 0.0
        model_type = "xgboost-regressor"

    manifest = {
        "modelType": model_type,
        "targetMode": resolved_target_mode,
        "horizonDays": horizon_days,
        "modelCount": trained_models,
        "trainedAtUtc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "trainPeriod": {"from": train_start.isoformat(), "to": train_end.isoformat()},
        "validationPeriod": {"from": validation_start.isoformat(), "to": validation_end.isoformat()},
        "featureColumns": FEATURE_COLUMNS,
        "meanAccuracy": mean_accuracy,
        "meanF1Macro": mean_f1_macro,
        "meanF1Buy": mean_f1_buy,
        "meanF1Hold": mean_f1_hold,
        "meanF1Sell": mean_f1_sell,
        "recencyWeightedTraining": bool(use_recency_weighting),
        "nEstimators": resolved_n_estimators,
        "learningRate": resolved_learning_rate,
        "symbols": sorted(symbol_metrics.keys()),
        "symbolMetrics": symbol_metrics,
        "skippedSymbols": skipped_symbols,
    }

    manifest_path = _manifest_path(model_root)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Clear in-memory model cache after new artifacts are persisted.
    with _MODEL_CACHE_LOCK:
        _MODEL_CACHE["modelDir"] = None
        _MODEL_CACHE["manifestMtime"] = None
        _MODEL_CACHE["manifest"] = {}
        _MODEL_CACHE["models"] = {}

    LOGGER.info(
        "Model training complete: trained=%s meanAccuracy=%.4f target=%s",
        trained_models,
        mean_accuracy,
        resolved_target_mode,
    )

    return manifest


def train_models_with_retry(
    attempts: int = 5,
    delay_seconds: float = 20.0,
    **kwargs: Any,
) -> dict[str, Any]:
    last_error: Exception | None = None

    for attempt in range(1, max(1, attempts) + 1):
        try:
            return train_xgboost_models(**kwargs)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            LOGGER.warning("Model training attempt %s/%s failed: %s", attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(delay_seconds)

    assert last_error is not None
    raise RuntimeError(f"Model training failed after {attempts} attempts: {last_error}") from last_error


def _load_manifest(model_dir: Path) -> dict[str, Any]:
    path = _manifest_path(model_dir)
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _load_models_from_manifest(model_dir: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    symbols = [str(item).upper() for item in manifest.get("symbols") or []]
    target_mode = normalize_target_mode(str(manifest.get("targetMode") or DEFAULT_TARGET_MODE))

    loaded: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        path = _model_path_for_symbol(model_dir, symbol, target_mode)
        if not path.exists():
            continue

        try:
            with path.open("rb") as model_file:
                payload = pickle.load(model_file)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Failed loading model for symbol %s: %s", symbol, exc)
            continue

        if isinstance(payload, dict) and payload.get("model") is not None:
            loaded[symbol] = payload

    return loaded


def _reload_model_cache_if_needed(model_dir: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    manifest_path = _manifest_path(model_dir)
    manifest_mtime = manifest_path.stat().st_mtime if manifest_path.exists() else None

    with _MODEL_CACHE_LOCK:
        same_dir = _MODEL_CACHE.get("modelDir") == str(model_dir)
        same_manifest = _MODEL_CACHE.get("manifestMtime") == manifest_mtime

        if same_dir and same_manifest and _MODEL_CACHE.get("manifest") and _MODEL_CACHE.get("models"):
            return _MODEL_CACHE["manifest"], _MODEL_CACHE["models"]

        manifest = _load_manifest(model_dir)
        models = _load_models_from_manifest(model_dir, manifest)

        _MODEL_CACHE["modelDir"] = str(model_dir)
        _MODEL_CACHE["manifestMtime"] = manifest_mtime
        _MODEL_CACHE["manifest"] = manifest
        _MODEL_CACHE["models"] = models

        return manifest, models


def predict_symbol_forecasts(
    as_of_date: date,
    symbols: list[str],
    model_dir: str | Path | None = None,
) -> ForecastBatch:
    normalized_symbols = sorted({symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()})
    if not normalized_symbols:
        return ForecastBatch(forecasts={}, warnings=["No symbols provided for ML forecast"], model_accuracy=0.0)

    model_root = _resolve_model_dir(model_dir)
    manifest, models = _reload_model_cache_if_needed(model_root)

    if not models:
        return ForecastBatch(
            forecasts={},
            warnings=[f"No trained ML models available in {model_root}"],
            model_accuracy=0.0,
        )

    raw = load_historical_market_data(
        symbols=normalized_symbols,
        start_date=DEFAULT_TRAIN_START,
        end_date=as_of_date,
    )
    latest_rows = build_latest_feature_rows(raw_frame=raw, as_of_date=as_of_date)

    latest_by_symbol: dict[str, pd.Series] = {}
    if not latest_rows.empty:
        latest_rows = latest_rows.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
        latest_by_symbol = {
            str(row["symbol"]).upper(): row
            for _, row in latest_rows.iterrows()
        }

    warnings: list[str] = []
    forecasts: dict[str, SymbolForecast] = {}
    accuracy_values: list[float] = []

    mean_accuracy_fallback = _safe_float(manifest.get("meanAccuracy"), 0.0)

    for symbol in normalized_symbols:
        payload = models.get(symbol)
        latest_row = latest_by_symbol.get(symbol)

        if payload is None:
            warnings.append(f"No trained model available for {symbol}")
            continue

        if latest_row is None:
            warnings.append(f"No feature row available for {symbol} as of {as_of_date.isoformat()}")
            continue

        feature_columns = payload.get("featureColumns") or FEATURE_COLUMNS
        model = payload.get("model")
        target_mode = normalize_target_mode(str(payload.get("targetMode") or manifest.get("targetMode") or DEFAULT_TARGET_MODE))

        if model is None:
            warnings.append(f"Model payload for {symbol} is invalid")
            continue

        x_row = pd.DataFrame([{column: _safe_float(latest_row.get(column), np.nan) for column in feature_columns}])
        if x_row.isna().any(axis=None):
            warnings.append(f"Feature row contains NaN values for {symbol}; forecast skipped")
            continue

        predicted_raw = float(model.predict(x_row)[0])
        current_close = _safe_float(latest_row.get("close_price"), 0.0)
        if current_close <= 0:
            warnings.append(f"Current close price is missing/invalid for {symbol}; forecast skipped")
            continue

        # Handle Classification vs Regression prediction logic
        if isinstance(model, XGBClassifier):
            # Classification Mode: Get class probabilities and predicted class
            class_proba = model.predict_proba(x_row)[0]  # Shape: (3,) for classes [0, 1, 2]
            predicted_class = int(np.argmax(class_proba))
            predicted_class_proba = float(class_proba[predicted_class])

            # Map predicted class to action and estimated return
            # Class 2 (BUY): return > 2%, Class 1 (HOLD): -1.5% to 2%, Class 0 (SELL): < -1.5%
            class_return_map = {0: -0.025, 1: 0.0, 2: 0.035}  # Conservative estimates for each class
            predicted_return = class_return_map[predicted_class]
            predicted_price = current_close * (1.0 + predicted_return)

            # Use predicted class probability as confidence score (e.g., 0.65 = 65% confidence)
            confidence = predicted_class_proba
            predicted_raw = float(predicted_class)
        else:
            # Regression Mode (original logic)
            if target_mode == "RETURN_PCT":
                predicted_return = predicted_raw
                predicted_price = current_close * (1.0 + predicted_return)
            else:
                predicted_price = predicted_raw
                predicted_return = (predicted_price / current_close) - 1.0

            predicted_class = 1  # Default HOLD for regression
            confidence = 0.5  # Default confidence for regression

        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        symbol_accuracy = _safe_float(metrics.get("accuracyScore"), mean_accuracy_fallback)

        # For classification, confidence is already the class probability
        # For regression, compute from tree uncertainty
        if not isinstance(model, XGBClassifier):
            tree_uncertainty_std = _estimate_tree_uncertainty_std(model, x_row)
            uncertainty_confidence = float(1.0 / (1.0 + (tree_uncertainty_std * 18.0)))
            confidence = float(np.clip((0.55 * symbol_accuracy) + (0.45 * uncertainty_confidence), 0.0, 1.0))

        influence_shares = _compute_local_feature_influence_shares(model, x_row, feature_columns)

        # Determine action based on predicted class or return
        if isinstance(model, XGBClassifier):
            action_map = {0: "SELL", 1: "HOLD", 2: "BUY"}
            action = action_map[predicted_class]
        else:
            # Regression fallback: derive action from predicted return
            if predicted_return <= -0.10:
                action = "PREVENTIVE_SELL"
            elif predicted_return < 0.0:
                action = "SELL"
            else:
                action = "HOLD"

        forecasts[symbol] = SymbolForecast(
            symbol=symbol,
            predicted_price_5d=predicted_price,
            predicted_return_5d=predicted_return,
            confidence_score=confidence,
            model_accuracy=symbol_accuracy,
            relative_volume_60d=_safe_float(latest_row.get("relative_volume_60d"), 1.0),
            market_sentiment_score=_safe_float(latest_row.get("market_sentiment_score"), 0.0),
            smart_money_signal=_safe_float(latest_row.get("smart_money_signal"), 0.0),
            global_factor_corr_sp500=_safe_float(latest_row.get("global_factor_corr_sp500"), 0.0),
            alt_news_sentiment_score=_safe_float(latest_row.get("alt_news_sentiment_score"), 0.0),
            alt_urea_price=_safe_float(latest_row.get("alt_urea_price"), 0.0),
            alt_brent_price=_safe_float(latest_row.get("alt_brent_price"), 0.0),
            alt_news_influence_share=_safe_float(influence_shares.get("alt_news_influence_share"), 0.0),
            alt_urea_influence_share=_safe_float(influence_shares.get("alt_urea_influence_share"), 0.0),
            alt_brent_influence_share=_safe_float(influence_shares.get("alt_brent_influence_share"), 0.0),
            predicted_class=predicted_class,
            action=action,
        )
        accuracy_values.append(symbol_accuracy)

    batch_accuracy = float(np.mean(accuracy_values)) if accuracy_values else mean_accuracy_fallback
    return ForecastBatch(forecasts=forecasts, warnings=warnings, model_accuracy=batch_accuracy)


def _build_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train and persist EGX XGBoost models")
    parser.add_argument("--model-dir", type=str, default="")
    parser.add_argument("--target-mode", type=str, default=os.getenv("AI_TARGET_MODE", DEFAULT_TARGET_MODE))
    parser.add_argument("--symbols", type=str, default="", help="Comma-separated symbols for scoped retraining")
    parser.add_argument("--horizon-days", type=int, default=DEFAULT_HORIZON_DAYS)
    parser.add_argument("--min-rows-per-symbol", type=int, default=DEFAULT_MIN_ROWS_PER_SYMBOL)
    parser.add_argument("--disable-recency-weighting", action="store_true")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--retry-delay-seconds", type=float, default=15.0)
    return parser.parse_args()


def _parse_symbols(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip().upper() for item in str(raw).split(",") if item and item.strip()]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = _build_cli_args()

    manifest = train_models_with_retry(
        attempts=max(1, args.attempts),
        delay_seconds=max(1.0, float(args.retry_delay_seconds)),
        model_dir=(args.model_dir.strip() or None),
        target_mode=args.target_mode,
        symbols=_parse_symbols(args.symbols),
        horizon_days=int(args.horizon_days),
        min_rows_per_symbol=int(args.min_rows_per_symbol),
        use_recency_weighting=not bool(args.disable_recency_weighting),
    )

    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
