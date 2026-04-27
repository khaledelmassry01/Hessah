#!/usr/bin/env python3
"""Test predict endpoint with relaxed thresholds."""
import requests
import json
from datetime import date

payload = {
    "request_id": "test-daily-sync-001",
    "user_id": "SYSTEM_TEST",
    "as_of_date": date.today().isoformat(),
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

print("=" * 60)
print("Testing /predict endpoint with RELAXED thresholds")
print(f"Date: {date.today().isoformat()}")
print("=" * 60)

try:
    print("\nCalling /predict endpoint...")
    r = requests.post("http://localhost:8002/predict", json=payload, timeout=120)
    print(f"Status Code: {r.status_code}")

    d = r.json()
    print(f"\nResponse Status: {d.get('status')}")
    print(f"Model Version: {d.get('model_version')}")
    print(f"Model Accuracy: {d.get('model_accuracy', 0):.4f}")
    print(f"\nAllocations: {len(d.get('allocations', []))}")
    print(f"Recommendations: {len(d.get('recommendations', []))}")

    warnings = d.get("warnings", [])
    print(f"\nWarnings ({len(warnings)}):")
    for w in warnings:
        print(f"  - {w}")

    allocations = d.get("allocations", [])
    if allocations:
        print("\n" + "=" * 60)
        print("ALLOCATIONS (Top 5):")
        print("=" * 60)
        for a in allocations[:5]:
            print(f"  {a.get('symbol')}: {a.get('weight', 0):.2%} (confidence: {a.get('confidence_score', 0):.2f})")
    else:
        print("\n⚠ No allocations returned - check warnings above")

    # Count by action
    recommendations = d.get("recommendations", [])
    action_counts = {}
    for rec in recommendations:
        action = rec.get("action", "UNKNOWN")
        action_counts[action] = action_counts.get(action, 0) + 1
    print(f"\nRecommendations by Action: {action_counts}")

    # Top BUYs
    buys = [(r.get("symbol"), r.get("confidence_score", 0)) for r in recommendations if r.get("action") == "BUY"]
    if buys:
        buys.sort(key=lambda x: x[1], reverse=True)
        print("\nTop BUY Recommendations:")
        for symbol, conf in buys[:5]:
            print(f"  {symbol}: confidence={conf:.2f}")

    print("\n" + "=" * 60)
    if allocations and len(allocations) > 0:
        print("✓ SUCCESS: Optimizer is selecting stocks!")
    else:
        print("⚠ PARTIAL: No allocations generated")
    print("=" * 60)

except Exception as e:
    print(f"\n❌ Error: {e}")
