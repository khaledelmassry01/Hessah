#!/usr/bin/env python3
"""
Generate today's AI predictions for all active EGX symbols.
This fixes the MarketWatch UNKNOWN/null actions by populating daily_ai_signals.
"""

import sys
import os

# Add app to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
LOGGER = logging.getLogger(__name__)

def main():
    from app.data_pipeline import load_market_dataset, canonicalize_symbol
    from app.model_training import predict_symbol_forecasts
    from app.prediction_feedback import log_prediction_batch
    from app.feature_engineering import load_historical_market_data, open_mysql_connection

    today = date.today()
    LOGGER.info("=" * 60)
    LOGGER.info("Generating AI predictions for %s", today.isoformat())
    LOGGER.info("=" * 60)

    # Load all available symbols from market data
    LOGGER.info("Loading market dataset...")
    dataset = load_market_dataset(
        as_of_date=today,
        max_adv30_participation=0.05,
        n_bars=252,
    )

    symbols = list(dataset.snapshots.keys())
    if not symbols:
        LOGGER.error("No symbols available in dataset")
        return 1

    LOGGER.info("Found %d eligible symbols", len(symbols))

    # Get predictions for all symbols
    LOGGER.info("Running ML predictions...")
    forecasts = predict_symbol_forecasts(
        as_of_date=today,
        symbols=symbols,
    )

    LOGGER.info("Generated forecasts for %d symbols", len(forecasts.forecasts))

    # Build predictions dict
    predictions = {}
    confidence_scores = {}
    actions = {}

    for symbol, forecast in forecasts.forecasts.items():
        predictions[symbol] = forecast.predicted_return_5d
        confidence_scores[symbol] = forecast.confidence_score
        actions[symbol] = getattr(forecast, 'action', 'HOLD')

    # Log to database
    LOGGER.info("Writing predictions to database...")
    rows_written = log_prediction_batch(
        as_of_date=today,
        predictions=predictions,
        confidence_scores=confidence_scores,
        request_id=f"daily-sync-{today.isoformat()}",
    )

    LOGGER.info("=" * 60)
    LOGGER.info("SUCCESS: Wrote %d prediction rows to database", rows_written)

    # Show summary by action
    action_counts = {}
    for symbol, action in actions.items():
        action_counts[action] = action_counts.get(action, 0) + 1

    LOGGER.info("Predictions by action: %s", action_counts)

    # Show top 5 BUY recommendations
    buys = [
        (symbol, forecasts.forecasts[symbol].predicted_return_5d, forecasts.forecasts[symbol].confidence_score)
        for symbol, action in actions.items()
        if action == "BUY"
    ]
    buys.sort(key=lambda x: x[2], reverse=True)  # Sort by confidence

    if buys:
        LOGGER.info("Top BUY recommendations:")
        for symbol, ret, conf in buys[:5]:
            LOGGER.info("  %s: return=%.2f%% confidence=%.2f", symbol, ret*100, conf)
    else:
        LOGGER.warning("No BUY signals generated - check confidence thresholds")

    LOGGER.info("=" * 60)
    return 0

if __name__ == "__main__":
    sys.exit(main())
