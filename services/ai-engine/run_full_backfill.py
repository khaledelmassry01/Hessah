"""
Master orchestration script for AI Model Data Backfill
Executes all backfill operations and triggers full model retraining.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger(__name__)


def run_script(script_name: str, description: str) -> bool:
    """Run a Python script and report results."""
    script_path = Path(__file__).parent / script_name

    LOGGER.info("=" * 60)
    LOGGER.info(f"Running: {description}")
    LOGGER.info(f"Script: {script_path}")
    LOGGER.info("=" * 60)

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=300,
        )

        # Log output
        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                LOGGER.info(f"  {line}")

        if result.stderr:
            for line in result.stderr.strip().split("\n"):
                LOGGER.warning(f"  STDERR: {line}")

        if result.returncode == 0:
            LOGGER.info(f"✅ {description} completed successfully")
            return True
        else:
            LOGGER.error(f"❌ {description} failed with code {result.returncode}")
            return False

    except subprocess.TimeoutExpired:
        LOGGER.error(f"⏱️ {description} timed out after 300 seconds")
        return False
    except Exception as e:
        LOGGER.error(f"💥 {description} failed with exception: {e}")
        return False


def main() -> int:
    """Execute full backfill pipeline."""
    LOGGER.info("=" * 60)
    LOGGER.info("AI MODEL DATA BACKFILL PIPELINE")
    LOGGER.info("=" * 60)

    scripts = [
        ("refresh_macro_data.py", "Macro Data Refresh (USD/EGP, CBE rates)"),
        ("backfill_commodities.py", "Commodity Data Backfill (Brent, Urea)"),
        ("backfill_sentiment.py", "Synthetic Sentiment Generation"),
    ]

    results = []
    for script, description in scripts:
        success = run_script(script, description)
        results.append((description, success))
        LOGGER.info("")

    # Summary
    LOGGER.info("=" * 60)
    LOGGER.info("BACKFILL PIPELINE SUMMARY")
    LOGGER.info("=" * 60)

    for description, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        LOGGER.info(f"  {status}: {description}")

    all_success = all(success for _, success in results)

    if all_success:
        LOGGER.info("=" * 60)
        LOGGER.info("🎉 ALL BACKFILLS COMPLETED SUCCESSFULLY!")
        LOGGER.info("=" * 60)
        LOGGER.info("")
        LOGGER.info("Next step: Trigger model retraining with:")
        LOGGER.info('  curl -X POST "http://localhost:8000/models/train?recency_weighted=true&n_estimators=500"')
        return 0
    else:
        LOGGER.error("=" * 60)
        LOGGER.error("⚠️ SOME BACKFILLS FAILED - CHECK LOGS ABOVE")
        LOGGER.error("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
