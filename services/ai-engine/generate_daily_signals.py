#!/usr/bin/env python3
"""
Daily AI Signal Generation Script

This script:
1. Loads both XGBoost classification and regression models from local volume
2. Fetches latest market data for all active symbols
3. Builds feature rows for all EGX30 symbols
4. Uses classification models for action/confidence
5. Uses regression models for predicted_return_5d
6. UPSERTs results to daily_ai_signals table
"""

import os
import sys
import logging
import pickle
import json
import numpy as np
import pandas as pd
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# Set up paths
sys.path.insert(0, str(Path(__file__).parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
LOGGER = logging.getLogger(__name__)

# Set environment variables
os.environ["AI_MODEL_DIR"] = str(Path(__file__).parent.parent.parent / "infra" / "models_data")
os.environ["DB_HOST"] = "127.0.0.1"
os.environ["DB_PORT"] = "3307"
os.environ["DB_USER"] = "egx_app_user"
os.environ["DB_PASSWORD"] = "EGX_App_7wN!9Qx2#M4Lz8"
os.environ["DB_NAME"] = "egx_portfolio"

from app.prediction_feedback import save_predictions_to_daily_signals
import mysql.connector


CLASSIFICATION_SUFFIXES = ("classification",)
REGRESSION_SUFFIXES = ("return_pct", "regression", "close_price")


def _load_model_payload(model_file: Path) -> tuple[Any | None, list[str], dict[str, Any]]:
    """Load a model payload from disk and normalize model/feature extraction."""
    with open(model_file, "rb") as f:
        payload = pickle.load(f)

    if isinstance(payload, dict):
        return payload.get("model"), payload.get("featureColumns", []), payload
    return payload, [], {}


def _load_symbol_model(
    model_dir: Path,
    symbol: str,
    mode_suffixes: tuple[str, ...],
) -> tuple[Any | None, list[str], Path | None]:
    """Load the first available model file for a symbol from candidate suffixes."""
    for suffix in mode_suffixes:
        model_file = model_dir / f"{symbol}_{suffix}_xgb.pkl"
        if not model_file.exists():
            continue

        try:
            model, feature_columns, _ = _load_model_payload(model_file)
            if model is None:
                LOGGER.warning(f"Model payload is empty for {model_file.name}")
                continue
            return model, feature_columns, model_file
        except Exception as e:
            LOGGER.warning(f"Failed to load {model_file.name}: {e}")

    return None, [], None


def load_models_from_disk(model_dir: Path) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    """Load both classification and regression models per symbol from model_dir."""
    manifest: dict[str, Any] = {}
    manifest_path = model_dir / "model_manifest.json"

    if manifest_path.exists():
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
    else:
        LOGGER.warning(f"Manifest not found: {manifest_path}. Falling back to file discovery.")

    manifest_symbols = [str(s).upper() for s in manifest.get("symbols", [])]
    discovered_classification_symbols = [
        p.name[: -len("_classification_xgb.pkl")].upper()
        for p in model_dir.glob("*_classification_xgb.pkl")
    ]
    symbols = sorted(set(manifest_symbols + discovered_classification_symbols))

    feature_columns = manifest.get("featureColumns", [])
    models: dict[str, Any] = {}

    LOGGER.info(f"Attempting dual-model load for {len(symbols)} symbols")
    for symbol in symbols:
        cls_model, cls_features, cls_file = _load_symbol_model(model_dir, symbol, CLASSIFICATION_SUFFIXES)
        reg_model, reg_features, reg_file = _load_symbol_model(model_dir, symbol, REGRESSION_SUFFIXES)

        if cls_model is None:
            LOGGER.warning(f"Missing classification model for {symbol}")
            continue
        if reg_model is None:
            LOGGER.warning(f"Missing regression model for {symbol}")
            continue

        models[symbol] = {
            "classification_model": cls_model,
            "regression_model": reg_model,
            "featureColumns": cls_features or reg_features or feature_columns,
            "classification_path": str(cls_file) if cls_file else None,
            "regression_path": str(reg_file) if reg_file else None,
        }

    LOGGER.info(
        "Successfully loaded %d dual-model symbol entries (classification + regression)",
        len(models),
    )
    return models, feature_columns, manifest


def fetch_latest_market_data_from_db(symbols: list[str], as_of_date: date) -> pd.DataFrame:
    """Fetch historical market data from database for feature engineering."""
    if not symbols:
        return pd.DataFrame()

    conn = mysql.connector.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
    )
    
    try:
        cursor = conn.cursor(dictionary=True)
        try:
            # Get symbol to stock_id mapping
            symbol_placeholders = ", ".join(["%s"] * len(symbols))
            cursor.execute(
                f"""
                SELECT id, symbol
                FROM stock_instruments
                WHERE symbol IN ({symbol_placeholders})
                """,
                symbols,
            )
            instrument_rows = cursor.fetchall()
            instruments = pd.DataFrame(instrument_rows)

            if instruments.empty:
                return pd.DataFrame()

            symbol_to_id = dict(zip(instruments["symbol"], instruments["id"]))
        
            # Fetch market data for last 252 days
            start_date = as_of_date - timedelta(days=366)
            stock_ids = list(symbol_to_id.values())
            if not stock_ids:
                return pd.DataFrame()

            stock_placeholders = ", ".join(["%s"] * len(stock_ids))
            cursor.execute(
                f"""
                SELECT
                    stock_id,
                    trade_date,
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    volume
                FROM market_daily_bars
                WHERE stock_id IN ({stock_placeholders})
                  AND trade_date BETWEEN %s AND %s
                ORDER BY stock_id, trade_date
                """,
                [*stock_ids, start_date, as_of_date],
            )
            market_rows = cursor.fetchall()
        finally:
            cursor.close()
        
        df = pd.DataFrame(market_rows)
        if df.empty:
            return df
        
        # Join back with symbols
        id_to_symbol = {v: k for k, v in symbol_to_id.items()}
        df["symbol"] = df["stock_id"].map(id_to_symbol)
        
        return df
    finally:
        conn.close()


def build_features(raw_df: pd.DataFrame, as_of_date: date) -> pd.DataFrame:
    """Build feature rows for prediction (simplified version)."""
    if raw_df.empty:
        return pd.DataFrame()
    
    # Ensure proper dtypes
    raw_df["trade_date"] = pd.to_datetime(raw_df["trade_date"])
    numeric_cols = ["open_price", "high_price", "low_price", "close_price", "volume"]
    for col in numeric_cols:
        if col in raw_df.columns:
            raw_df[col] = pd.to_numeric(raw_df[col], errors="coerce")
    
    features_list = []
    
    for symbol, group in raw_df.groupby("symbol"):
        group = group.sort_values("trade_date").reset_index(drop=True)
        if len(group) < 60:  # Need minimum history
            LOGGER.warning(f"Insufficient history for {symbol}: {len(group)} rows")
            continue
        
        # Get latest row
        latest = group.iloc[-1].copy()
        
        # Calculate technical features
        close = group["close_price"].astype(float)
        high = group["high_price"].astype(float)
        low = group["low_price"].astype(float)
        volume = group["volume"].astype(float)
        
        # Daily return
        daily_return = close.pct_change().iloc[-1]
        
        # Lagged returns
        return_1d_lag1 = close.pct_change().shift(1).iloc[-1]
        return_1d_lag2 = close.pct_change().shift(2).iloc[-1]
        return_1d_lag3 = close.pct_change().shift(3).iloc[-1]
        
        # EMAs
        ema_20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
        ema_50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
        ema_200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
        ema_200_distance = (close.iloc[-1] / ema_200 - 1.0) if ema_200 > 0 else 0.0
        
        # RSI (14)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi_14 = (100 - (100 / (1 + rs))).iloc[-1]
        
        # MACD
        ema_12 = close.ewm(span=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, adjust=False).mean()
        macd = (ema_12 - ema_26).iloc[-1]
        macd_signal = macd.ewm(span=9, adjust=False).mean().iloc[-1] if hasattr(macd, 'ewm') else 0
        macd_hist = macd - macd_signal
        
        # Bollinger Bands
        sma_20 = close.rolling(window=20).mean()
        std_20 = close.rolling(window=20).std()
        bollinger_mid = sma_20.iloc[-1]
        bollinger_upper = (sma_20 + 2 * std_20).iloc[-1]
        bollinger_lower = (sma_20 - 2 * std_20).iloc[-1]
        bollinger_width = (bollinger_upper - bollinger_lower) / bollinger_mid if bollinger_mid > 0 else 0
        
        # ATR
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr_14 = true_range.rolling(window=14).mean().iloc[-1]
        atr_14_pct = atr_14 / close.iloc[-1] if close.iloc[-1] > 0 else 0
        
        # Volume features
        volume_20d_avg = volume.rolling(window=20, min_periods=5).mean().iloc[-1]
        volume_shock_20d = (volume.iloc[-1] / volume_20d_avg - 1.0) if volume_20d_avg > 0 else 0
        volume_60d_avg = volume.rolling(window=60, min_periods=20).mean().iloc[-1]
        relative_volume_60d = (volume.iloc[-1] / volume_60d_avg) if volume_60d_avg > 0 else 1.0
        
        # Sector momentum (simplified - just use price momentum)
        sector_momentum_5d = close.pct_change(5).iloc[-1]
        
        # Market sentiment placeholder
        market_sentiment_score = 0.0
        smart_money_signal = 0.0
        global_factor_corr_sp500 = 0.0
        
        # Alternative data placeholders
        alt_news_sentiment_score = 0.0
        alt_urea_price = 0.0
        alt_urea_return_1d = 0.0
        alt_urea_return_5d = 0.0
        alt_urea_zscore_20d = 0.0
        alt_brent_price = 0.0
        alt_brent_return_1d = 0.0
        alt_brent_return_5d = 0.0
        alt_brent_zscore_20d = 0.0
        
        # USD/EGP and Gold placeholders
        usd_egp_return = 0.0
        gold_return = 0.0
        stock_usd_corr_20d = 0.0
        
        # CBE rate placeholders
        cbe_policy_rate_pct = 0.0
        cbe_rate_changed = 0.0
        
        # RSI divergence
        rsi_divergence_14 = 0.0  # Simplified
        
        features = {
            "symbol": symbol,
            "trade_date": latest["trade_date"],
            "close_price": float(close.iloc[-1]),
            "daily_return": float(daily_return) if not np.isnan(daily_return) else 0.0,
            "return_1d_lag1": float(return_1d_lag1) if not np.isnan(return_1d_lag1) else 0.0,
            "return_1d_lag2": float(return_1d_lag2) if not np.isnan(return_1d_lag2) else 0.0,
            "return_1d_lag3": float(return_1d_lag3) if not np.isnan(return_1d_lag3) else 0.0,
            "ema_20": float(ema_20) if not np.isnan(ema_20) else close.iloc[-1],
            "ema_50": float(ema_50) if not np.isnan(ema_50) else close.iloc[-1],
            "ema_200": float(ema_200) if not np.isnan(ema_200) else close.iloc[-1],
            "ema_200_distance": float(ema_200_distance) if not np.isnan(ema_200_distance) else 0.0,
            "rsi_14": float(rsi_14) if not np.isnan(rsi_14) else 50.0,
            "rsi_divergence_14": float(rsi_divergence_14),
            "macd": float(macd) if not np.isnan(macd) else 0.0,
            "macd_signal": float(macd_signal) if not np.isnan(macd_signal) else 0.0,
            "macd_hist": float(macd_hist) if not np.isnan(macd_hist) else 0.0,
            "bollinger_mid_20": float(bollinger_mid) if not np.isnan(bollinger_mid) else close.iloc[-1],
            "bollinger_upper_20": float(bollinger_upper) if not np.isnan(bollinger_upper) else close.iloc[-1],
            "bollinger_lower_20": float(bollinger_lower) if not np.isnan(bollinger_lower) else close.iloc[-1],
            "bollinger_width_20": float(bollinger_width) if not np.isnan(bollinger_width) else 0.0,
            "atr_14": float(atr_14) if not np.isnan(atr_14) else 0.0,
            "atr_14_pct": float(atr_14_pct) if not np.isnan(atr_14_pct) else 0.0,
            "usd_egp_return": float(usd_egp_return),
            "gold_return": float(gold_return),
            "stock_usd_corr_20d": float(stock_usd_corr_20d),
            "sector_momentum_5d": float(sector_momentum_5d) if not np.isnan(sector_momentum_5d) else 0.0,
            "volume_shock_20d": float(volume_shock_20d) if not np.isnan(volume_shock_20d) else 0.0,
            "relative_volume_60d": float(relative_volume_60d) if not np.isnan(relative_volume_60d) else 1.0,
            "market_sentiment_score": float(market_sentiment_score),
            "global_factor_corr_sp500": float(global_factor_corr_sp500),
            "smart_money_signal": float(smart_money_signal),
            "cbe_policy_rate_pct": float(cbe_policy_rate_pct),
            "cbe_rate_changed": float(cbe_rate_changed),
            "alt_news_sentiment_score": float(alt_news_sentiment_score),
            "alt_urea_price": float(alt_urea_price),
            "alt_urea_return_1d": float(alt_urea_return_1d),
            "alt_urea_return_5d": float(alt_urea_return_5d),
            "alt_urea_zscore_20d": float(alt_urea_zscore_20d),
            "alt_brent_price": float(alt_brent_price),
            "alt_brent_return_1d": float(alt_brent_return_1d),
            "alt_brent_return_5d": float(alt_brent_return_5d),
            "alt_brent_zscore_20d": float(alt_brent_zscore_20d),
        }
        features_list.append(features)
    
    return pd.DataFrame(features_list)


def run_predictions(models: dict, feature_columns: list, as_of_date: date) -> list[dict]:
    """Run classification + regression predictions for all symbols."""

    # Fetch historical data for feature engineering
    raw_data = fetch_latest_market_data_from_db(list(models.keys()), as_of_date)
    
    if raw_data.empty:
        LOGGER.error("No market data available")
        return []
    
    LOGGER.info(f"Fetched {len(raw_data)} rows of market data")
    
    # Build features
    features_df = build_features(raw_data, as_of_date)
    
    if features_df.empty:
        LOGGER.error("No features built")
        return []
    
    LOGGER.info(f"Built features for {len(features_df)} symbols")
    
    recommendations = []
    
    for _, row in features_df.iterrows():
        symbol = row["symbol"]
        model_data = models.get(symbol)
        
        if not model_data:
            LOGGER.warning(f"No model for {symbol}")
            continue

        classification_model = model_data.get("classification_model")
        regression_model = model_data.get("regression_model")
        if classification_model is None or regression_model is None:
            LOGGER.warning(f"Incomplete model pair for {symbol}")
            continue

        symbol_feature_columns = model_data.get("featureColumns") or feature_columns
        if not symbol_feature_columns:
            LOGGER.warning(f"No feature columns available for {symbol}")
            continue

        # Build feature row
        x_row = pd.DataFrame([{col: float(row.get(col, 0.0)) for col in symbol_feature_columns}])
        
        if x_row.isna().any(axis=None):
            LOGGER.warning(f"NaN values in features for {symbol}")
            continue
        
        try:
            # Classification output: action + confidence
            class_proba = classification_model.predict_proba(x_row.to_numpy())[0]
            predicted_class = int(np.argmax(class_proba))
            predicted_class_proba = float(class_proba[predicted_class])

            # Map class to action
            action_map = {0: "SELL", 1: "HOLD", 2: "BUY"}
            action = action_map[predicted_class]

            # Confidence score is the predicted class probability
            confidence = predicted_class_proba

            # Regression output: continuous expected 5-day return
            predicted_return_5d = float(regression_model.predict(x_row.to_numpy())[0])
            if not np.isfinite(predicted_return_5d):
                LOGGER.warning(f"Non-finite regression output for {symbol}")
                continue
            
            recommendations.append({
                "symbol": symbol,
                "action": action,
                "confidence_score": round(confidence, 6),
                "predicted_return_5d": round(predicted_return_5d, 6),
                "predicted_class": predicted_class,
                "close_price": float(row["close_price"]),
            })

            LOGGER.info(
                "%s: %s (confidence=%.4f, predicted_return_5d=%.6f)",
                symbol,
                action,
                confidence,
                predicted_return_5d,
            )
            
        except Exception as e:
            LOGGER.error(f"Prediction failed for {symbol}: {e}")
    
    return recommendations


def main() -> int:
    """Main entry point."""
    today = date.today()
    LOGGER.info(f"=" * 60)
    LOGGER.info(f"Daily AI Signal Generation - {today}")
    LOGGER.info(f"=" * 60)
    
    # Load models
    model_dir = Path(os.environ["AI_MODEL_DIR"])
    LOGGER.info(f"Model directory: {model_dir}")
    
    models, feature_columns, manifest = load_models_from_disk(model_dir)
    
    if not models:
        LOGGER.error("No models loaded")
        return 1
    
    LOGGER.info(f"Feature columns: {len(feature_columns)}")
    
    # Run predictions
    recommendations = run_predictions(models, feature_columns, today)
    
    if not recommendations:
        LOGGER.error("No recommendations generated")
        return 1
    
    LOGGER.info(f"Generated {len(recommendations)} recommendations")
    
    # Save to database
    model_version = f"{manifest.get('modelType', 'xgboost')}-dual-mode-v1"
    saved_count = save_predictions_to_daily_signals(
        signal_date=today,
        recommendations=recommendations,
        model_version=model_version,
    )
    
    LOGGER.info(f"Saved {saved_count} signals to daily_ai_signals table")
    
    # Verify
    conn = mysql.connector.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
    )
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM daily_ai_signals WHERE signal_date = %s",
            (today,)
        )
        count = cursor.fetchone()[0]
        LOGGER.info(f"Verification: {count} signals in database for today")
        
        cursor.execute(
            """SELECT symbol, action, confidence_score, predicted_return_5d 
               FROM daily_ai_signals 
               WHERE signal_date = %s 
               ORDER BY confidence_score DESC 
               LIMIT 10""",
            (today,)
        )
        rows = cursor.fetchall()
        LOGGER.info("Top signals by confidence:")
        for r in rows:
            confidence = float(r[2]) if r[2] is not None else 0.0
            predicted = float(r[3]) if r[3] is not None else float("nan")
            LOGGER.info(f"  {r[0]}: {r[1]} (confidence={confidence:.4f}, predicted_return_5d={predicted:.6f})")
    finally:
        conn.close()
    
    LOGGER.info("=" * 60)
    LOGGER.info("SUCCESS: Daily AI signals generated and saved")
    LOGGER.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
