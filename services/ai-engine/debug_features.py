#!/usr/bin/env python3
"""Debug feature engineering pipeline."""
import os
import sys
import logging
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
LOGGER = logging.getLogger(__name__)

os.environ["DB_HOST"] = "127.0.0.1"
os.environ["DB_PORT"] = "3307"
os.environ["DB_USER"] = "egx_app_user"
os.environ["DB_PASSWORD"] = "EGX_App_7wN!9Qx2#M4Lz8"
os.environ["DB_NAME"] = "egx_portfolio"

from app.feature_engineering import load_historical_market_data, add_technical_indicators, add_contextual_features
from app.data_pipeline import EGX30_CANONICAL_SYMBOLS

def main():
    LOGGER.info("Loading data...")
    raw = load_historical_market_data(
        symbols=EGX30_CANONICAL_SYMBOLS[:3],  # Just 3 symbols for debugging
        start_date=date(2024, 1, 1),
        end_date=date(2026, 4, 27),
    )
    LOGGER.info(f"Raw data: {len(raw)} rows, columns: {list(raw.columns)}")
    LOGGER.info(f"First few rows:\n{raw.head()}")
    
    LOGGER.info("Adding technical indicators...")
    with_tech = add_technical_indicators(raw)
    LOGGER.info(f"After technical indicators: {len(with_tech)} rows, columns: {list(with_tech.columns)}")
    LOGGER.info(f"First few rows:\n{with_tech.head()}")
    
    if 'symbol' not in with_tech.columns:
        LOGGER.error("ERROR: 'symbol' column missing after technical indicators!")
        return 1
    
    LOGGER.info("Adding contextual features...")
    with_context = add_contextual_features(with_tech)
    LOGGER.info(f"After contextual features: {len(with_context)} rows, columns: {list(with_context.columns)}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
