#!/usr/bin/env python3
"""
Trigger today's AI predictions via the AI Engine API.
This populates daily_ai_signals to fix MarketWatch UNKNOWN/null actions.
"""

import json
from datetime import date

try:
    import requests
except ImportError:
    print("Installing requests...")
    import subprocess
    subprocess.check_call(["pip", "install", "requests", "-q"])
    import requests

AI_ENGINE_URL = "http://localhost:8002"  # Docker mapped port

def main():
    today = date.today().isoformat()

    print("=" * 60)
    print(f"Triggering AI Predictions for {today}")
    print("=" * 60)

    # First check health
    try:
        resp = requests.get(f"{AI_ENGINE_URL}/health", timeout=5)
        print(f"AI Engine Health: {resp.json()}")
    except Exception as e:
        print(f"ERROR: Cannot connect to AI Engine at {AI_ENGINE_URL}")
        print(f"Error: {e}")
        print("\nMake sure the Docker container is running:")
        print("  docker compose up -d ai-engine")
        return 1

    # Call predict endpoint
    payload = {
        "request_id": f"daily-sync-{today}",
        "user_id": "SYSTEM_RADAR",
        "as_of_date": today,
        "budget_egp": "1000000.00",
        "risk_level": "MEDIUM",
        "tier": "PREMIUM",
        "constraints": {
            "max_sector_weight": "0.40",
            "max_adv30_participation": "0.05",
            "exclude_suspended": True,
            "allow_fractional_shares": False,
        },
    }

    print(f"\nCalling /predict endpoint...")
    resp = requests.post(
        f"{AI_ENGINE_URL}/predict",
        json=payload,
        timeout=120
    )
    resp.raise_for_status()
    result = resp.json()

    print(f"\nStatus: {result.get('status')}")
    print(f"Model Version: {result.get('model_version')}")
    print(f"Model Accuracy: {result.get('model_accuracy', 0):.4f}")

    allocations = result.get('allocations', [])
    recommendations = result.get('recommendations', [])
    warnings = result.get('warnings', [])

    print(f"\nAllocations: {len(allocations)}")
    print(f"Recommendations: {len(recommendations)}")

    # Count by action
    action_counts = {}
    for rec in recommendations:
        action = rec.get('action', 'UNKNOWN')
        action_counts[action] = action_counts.get(action, 0) + 1

    print(f"\nBy Action: {action_counts}")

    # Show top BUY recommendations
    buys = [
        (rec['symbol'], rec.get('predicted_return_5d', 0), rec.get('confidence_score', 0))
        for rec in recommendations
        if rec.get('action') == 'BUY'
    ]
    buys.sort(key=lambda x: x[2], reverse=True)

    if buys:
        print("\nTop BUY Recommendations:")
        for symbol, ret, conf in buys[:5]:
            print(f"  {symbol}: return={ret*100:.2f}%, confidence={conf:.2f}")
    else:
        print("\nNo BUY signals generated (check confidence thresholds)")

    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for w in warnings[:5]:
            print(f"  - {w}")

    # Check model training status
    print("\n" + "=" * 60)
    print("Checking Model Training Status...")
    resp = requests.get(f"{AI_ENGINE_URL}/models/status", timeout=10)
    status = resp.json()
    print(f"Status: {status.get('status')}")

    latest = status.get('latestTraining', {})
    if latest:
        print(f"  Models Trained: {latest.get('modelCount', 0)}")
        print(f"  Mean Accuracy: {latest.get('meanAccuracy', 0):.4f}")
        print(f"  Mean F1 Macro: {latest.get('meanF1Macro', 0):.4f}")
        print(f"  Trained At: {latest.get('trainedAtUtc', 'N/A')}")
    else:
        print("  No training summary available!")
        print("\n  To train models, run:")
        print(f'    curl -X POST "{AI_ENGINE_URL}/models/train"')

    print("=" * 60)

    if result.get('status') in ('SUCCESS', 'PARTIAL') and allocations:
        print("\n✓ SUCCESS: Daily signals generated and written to database")
        return 0
    else:
        print("\n⚠ PARTIAL/FAILURE: Check warnings above")
        return 1

if __name__ == "__main__":
    exit(main())
