from __future__ import annotations

import argparse
import json
import logging
import os
import pickle
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .feature_engineering import FEATURE_COLUMNS, build_latest_feature_rows, load_historical_market_data
from .prediction_feedback import save_predictions_to_daily_signals

LOGGER = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = Path("/app/models")
CLASSIFICATION_SUFFIXES = ("classification",)
REGRESSION_SUFFIXES = ("return_pct", "regression", "close_price")
ACTION_MAP = {0: "SELL", 1: "HOLD", 2: "BUY"}


def _resolve_model_dir(model_dir: str | Path | None) -> Path:
    if model_dir is None:
        configured = (os.getenv("AI_MODEL_DIR") or str(DEFAULT_MODEL_DIR)).strip()
        return Path(configured)
    return Path(model_dir)


class PredictionService:
    """Unified prediction service that scores symbols with both classification and regression models."""

    def __init__(self, model_dir: str | Path | None = None) -> None:
        self.model_dir = _resolve_model_dir(model_dir)

    def _load_manifest(self) -> dict[str, Any]:
        manifest_path = self.model_dir / "model_manifest.json"
        if not manifest_path.exists():
            return {}

        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Failed reading model manifest %s: %s", manifest_path, exc)
            return {}

    @staticmethod
    def _load_model_payload(model_file: Path) -> tuple[Any | None, list[str], dict[str, Any]]:
        with model_file.open("rb") as handle:
            payload = pickle.load(handle)

        if isinstance(payload, dict):
            return payload.get("model"), list(payload.get("featureColumns") or []), payload
        return payload, [], {}

    def _load_symbol_model(
        self,
        symbol: str,
        mode_suffixes: tuple[str, ...],
    ) -> tuple[Any | None, list[str], Path | None]:
        for suffix in mode_suffixes:
            model_file = self.model_dir / f"{symbol}_{suffix}_xgb.pkl"
            if not model_file.exists():
                continue

            try:
                model, feature_columns, _ = self._load_model_payload(model_file)
                if model is None:
                    LOGGER.warning("Model payload is empty for %s", model_file.name)
                    continue
                return model, feature_columns, model_file
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Failed to load model %s: %s", model_file.name, exc)

        return None, [], None

    def load_model_pairs(
        self,
        symbols: list[str] | None = None,
    ) -> tuple[dict[str, dict[str, Any]], list[str]]:
        manifest = self._load_manifest()
        manifest_symbols = [str(item).upper() for item in manifest.get("symbols") or []]
        discovered_classification_symbols = [
            path.name[: -len("_classification_xgb.pkl")].upper()
            for path in self.model_dir.glob("*_classification_xgb.pkl")
        ]

        candidate_symbols = sorted(set(manifest_symbols + discovered_classification_symbols))
        requested_symbols = sorted({str(item).upper() for item in (symbols or []) if str(item).strip()})
        if requested_symbols:
            candidate_symbols = [symbol for symbol in candidate_symbols if symbol in set(requested_symbols)]

        warnings: list[str] = []
        model_pairs: dict[str, dict[str, Any]] = {}
        manifest_features = list(manifest.get("featureColumns") or [])

        for symbol in candidate_symbols:
            classification_model, cls_features, cls_file = self._load_symbol_model(symbol, CLASSIFICATION_SUFFIXES)
            regression_model, reg_features, reg_file = self._load_symbol_model(symbol, REGRESSION_SUFFIXES)

            if classification_model is None:
                warnings.append(f"Missing classification model for {symbol}")
                continue
            if regression_model is None:
                warnings.append(f"Missing regression model for {symbol}")
                continue

            model_pairs[symbol] = {
                "classification_model": classification_model,
                "regression_model": regression_model,
                "featureColumns": cls_features or reg_features or manifest_features or FEATURE_COLUMNS,
                "classification_path": str(cls_file) if cls_file else None,
                "regression_path": str(reg_file) if reg_file else None,
            }

        return model_pairs, warnings

    @staticmethod
    def _build_latest_features(symbols: list[str], as_of_date: date) -> pd.DataFrame:
        if not symbols:
            return pd.DataFrame()

        start_date = as_of_date - timedelta(days=420)
        raw = load_historical_market_data(
            symbols=symbols,
            start_date=start_date,
            end_date=as_of_date,
        )
        if raw.empty:
            return pd.DataFrame()

        latest = build_latest_feature_rows(raw_frame=raw, as_of_date=as_of_date)
        if latest.empty:
            return latest

        latest = latest.copy()
        latest["symbol"] = latest["symbol"].astype(str).str.upper()
        return latest

    def predict_symbols(
        self,
        as_of_date: date,
        symbols: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        model_pairs, warnings = self.load_model_pairs(symbols=symbols)
        if not model_pairs:
            return [], warnings + [f"No model pairs available in {self.model_dir}"]

        latest_rows = self._build_latest_features(list(model_pairs.keys()), as_of_date=as_of_date)
        if latest_rows.empty:
            return [], warnings + ["No feature rows available for requested symbols"]

        latest_by_symbol = {
            str(row["symbol"]).upper(): row
            for _, row in latest_rows.iterrows()
        }

        predictions: list[dict[str, Any]] = []
        for symbol, pair in sorted(model_pairs.items(), key=lambda item: item[0]):
            latest_row = latest_by_symbol.get(symbol)
            if latest_row is None:
                warnings.append(f"No latest feature row available for {symbol}")
                continue

            feature_columns = list(pair.get("featureColumns") or FEATURE_COLUMNS)
            x_row = pd.DataFrame([{column: float(latest_row.get(column, 0.0)) for column in feature_columns}])
            if x_row.isna().any(axis=None):
                warnings.append(f"NaN values in feature row for {symbol}")
                continue

            try:
                classification_model = pair["classification_model"]
                regression_model = pair["regression_model"]

                class_proba = classification_model.predict_proba(x_row.to_numpy())[0]
                predicted_class = int(np.argmax(class_proba))
                confidence_score = float(class_proba[predicted_class])

                predicted_return_5d = float(regression_model.predict(x_row.to_numpy())[0])
                if not np.isfinite(predicted_return_5d):
                    warnings.append(f"Non-finite predicted return for {symbol}")
                    continue

                predictions.append(
                    {
                        "symbol": symbol,
                        "action": ACTION_MAP.get(predicted_class, "HOLD"),
                        "confidence_score": round(confidence_score, 6),
                        "predicted_return_5d": round(predicted_return_5d, 6),
                        "predicted_class": predicted_class,
                        "close_price": float(latest_row.get("close_price", 0.0)),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Prediction failed for {symbol}: {exc}")

        return predictions, warnings

    def generate_daily_signals(
        self,
        as_of_date: date | None = None,
        symbols: list[str] | None = None,
        model_version: str = "xgb-dual-mode-v1",
    ) -> dict[str, Any]:
        signal_date = as_of_date or date.today()
        predictions, warnings = self.predict_symbols(as_of_date=signal_date, symbols=symbols)

        saved_count = 0
        if predictions:
            saved_count = save_predictions_to_daily_signals(
                signal_date=signal_date,
                recommendations=predictions,
                model_version=model_version,
            )

        return {
            "signalDate": signal_date.isoformat(),
            "predictions": predictions,
            "predictionCount": len(predictions),
            "savedCount": int(saved_count),
            "warnings": warnings,
        }


def _parse_symbols(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip().upper() for item in str(raw).split(",") if item and item.strip()]


def _build_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run unified daily AI signal prediction service")
    parser.add_argument("--date", type=str, default="", help="Signal date in YYYY-MM-DD format")
    parser.add_argument("--symbols", type=str, default="", help="Comma-separated symbols")
    parser.add_argument("--model-dir", type=str, default="")
    parser.add_argument("--model-version", type=str, default="xgb-dual-mode-v1")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = _build_cli_args()

    signal_date = date.fromisoformat(args.date) if args.date else date.today()
    service = PredictionService(model_dir=(args.model_dir.strip() or None))
    result = service.generate_daily_signals(
        as_of_date=signal_date,
        symbols=_parse_symbols(args.symbols),
        model_version=args.model_version,
    )

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
