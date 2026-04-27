#!/bin/sh
set -e

export HISTORICAL_DATA_DIR="${HISTORICAL_DATA_DIR:-/app/data/historical}"

mkdir -p "$HISTORICAL_DATA_DIR"

if [ "${HISTORICAL_SEED_ON_STARTUP:-true}" = "true" ]; then
	# Seed in the background so API startup is not blocked by upstream provider delays/rate limits.
	python /app/data_seeder.py --if-empty --years "${HISTORICAL_YEARS:-10}" --delay-seconds "${HISTORICAL_SEED_DELAY_SECONDS:-0.25}" &
fi

# Generate today's AI signals if both classification and regression models exist
if ls /app/models/*_classification_xgb.pkl >/dev/null 2>&1 && ls /app/models/*_return_pct_xgb.pkl >/dev/null 2>&1; then
	echo "Generating today's AI signals..."
	python -m app.prediction_service --model-version "xgb-egx30-v1" || echo "Signal generation failed, continuing..."
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
