#!/usr/bin/env python3
"""
Train Regression Models for all EGX30 Symbols

This trains XGBRegressor models to predict continuous return values (predicted_return_5d).
These will be used alongside the Classification models for the daily signal sync.
"""

import os
import sys
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

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

from app.model_training import train_xgboost_models
from app.data_pipeline import EGX30_CANONICAL_SYMBOLS


def main() -> int:
    """Train regression models for all EGX30 symbols."""
    LOGGER.info("=" * 70)
    LOGGER.info("Training Regression Models (target_mode=RETURN_PCT)")
    LOGGER.info("=" * 70)
    
    model_dir = Path(os.environ["AI_MODEL_DIR"])
    LOGGER.info(f"Model directory: {model_dir}")
    LOGGER.info(f"Symbols to train: {len(EGX30_CANONICAL_SYMBOLS)}")
    LOGGER.info(f"First 5 symbols: {EGX30_CANONICAL_SYMBOLS[:5]}")
    
    # First check what data we have
    from app.feature_engineering import load_historical_market_data
    raw_test = load_historical_market_data(
        symbols=EGX30_CANONICAL_SYMBOLS[:5],
        start_date=date(2024, 1, 1),
        end_date=date(2026, 4, 27),
    )
    LOGGER.info(f"Test data load: {len(raw_test)} rows, columns: {list(raw_test.columns)}")
    if not raw_test.empty:
        LOGGER.info(f"Sample data:\n{raw_test.head()}")
    
    # Train regression models
    result = train_xgboost_models(
        model_dir=model_dir,
        target_mode="RETURN_PCT",  # Regression mode - predict continuous returns
        symbols=EGX30_CANONICAL_SYMBOLS,
        horizon_days=5,
        min_rows_per_symbol=120,
    )
    
    LOGGER.info("=" * 70)
    LOGGER.info(f"Training completed: {result}")
    LOGGER.info("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
