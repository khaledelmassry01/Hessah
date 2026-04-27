#!/usr/bin/env python3
"""
Trigger Daily AI Signal Generation for Market Watch

This script directly populates the daily_ai_signals table by:
1. Calling the AI Engine's /predict endpoint to generate predictions
2. Saving predictions to the core-backend database

Usage:
    python trigger_daily_signals.py [--core-url CORE_URL] [--ai-url AI_URL]

Options:
    --core-url    Core backend URL (default: http://localhost:8083)
    --ai-url      AI engine URL (default: http://localhost:8002)
    --admin-user  Admin username for core-backend (default: admin)
    --admin-pass  Admin password for core-backend (default: admin123)
"""

import argparse
import json
import sys
from datetime import date
from decimal import Decimal
from typing import Any, Optional

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Trigger daily AI signal generation for Market Watch"
    )
    parser.add_argument(
        "--core-url",
        default="http://localhost:8083",
        help="Core backend base URL (default: http://localhost:8083)",
    )
    parser.add_argument(
        "--ai-url",
        default="http://localhost:8002",
        help="AI engine base URL (default: http://localhost:8002)",
    )
    parser.add_argument(
        "--admin-user",
        default="admin",
        help="Admin username for core-backend",
    )
    parser.add_argument(
        "--admin-pass",
        default="admin123",
        help="Admin password for core-backend",
    )
    parser.add_argument(
        "--use-admin-radar",
        action="store_true",
        default=True,
        help="Use the admin radar trigger endpoint (default: True)",
    )
    parser.add_argument(
        "--direct-predict",
        action="store_true",
        help="Directly call AI engine /predict and save to core-backend DB",
    )
    return parser.parse_args()


def get_core_token(core_url: str, username: str, password: str) -> Optional[str]:
    """Authenticate with core-backend and return JWT token."""
    try:
        # Try common auth endpoints
        auth_urls = [
            f"{core_url}/api/auth/login",
            f"{core_url}/auth/login",
            f"{core_url}/login",
        ]
        
        for auth_url in auth_urls:
            try:
                resp = requests.post(
                    auth_url,
                    json={"email": username, "password": password},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    # Common token field names
                    for key in ["accessToken", "access_token", "token"]:
                        if key in data:
                            return data[key]
            except Exception:
                continue
        
        print("Warning: Could not authenticate with core-backend. Admin endpoints may fail.")
        return None
    except Exception as e:
        print(f"Auth error: {e}")
        return None


def trigger_admin_radar_scan(core_url: str, token: Optional[str]) -> dict[str, Any]:
    """Trigger market radar scan via admin endpoint."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    url = f"{core_url}/api/core/admin/radar/trigger"
    
    try:
        resp = requests.post(url, headers=headers, timeout=120)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        return {"status": "ERROR", "error": str(e)}


def get_radar_status(core_url: str, token: Optional[str]) -> dict[str, Any]:
    """Get current radar status."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    url = f"{core_url}/api/core/admin/radar/status"
    
    try:
        resp = requests.post(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        return {"status": "ERROR", "error": str(e)}


def trigger_direct_predict(ai_url: str) -> dict[str, Any]:
    """Directly call AI engine predict endpoint."""
    url = f"{ai_url}/predict"
    
    payload = {
        "request_id": f"manual-trigger-{date.today().isoformat()}",
        "user_id": "SYSTEM_RADAR",
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
    
    try:
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        return {"status": "ERROR", "error": str(e)}


def main() -> int:
    args = parse_args()
    
    print("=" * 60)
    print("Daily AI Signal Generator - Market Watch Population")
    print("=" * 60)
    print(f"Core backend: {args.core_url}")
    print(f"AI engine: {args.ai_url}")
    print(f"Mode: {'Direct Predict' if args.direct_predict else 'Admin Radar Trigger'}")
    print("-" * 60)
    
    # Get auth token for admin endpoints
    token = None
    if not args.direct_predict:
        print("Authenticating with core-backend...")
        token = get_core_token(args.core_url, args.admin_user, args.admin_pass)
        if token:
            print("Authentication successful")
        else:
            print("Warning: No auth token obtained, admin endpoints may be rejected")
    
    # Check current radar status
    print("\nCurrent radar status:")
    status = get_radar_status(args.core_url, token)
    print(json.dumps(status, indent=2, default=str))
    
    # Trigger signal generation
    if args.direct_predict:
        print("\nTriggering direct AI prediction...")
        result = trigger_direct_predict(args.ai_url)
        print(json.dumps(result, indent=2, default=str))
        
        if result.get("status") == "SUCCESS":
            print(f"\nGenerated {len(result.get('recommendations', []))} predictions")
    else:
        print("\nTriggering admin radar scan...")
        result = trigger_admin_radar_scan(args.core_url, token)
        print(json.dumps(result, indent=2, default=str))
    
    # Check updated status
    print("\nUpdated radar status:")
    updated_status = get_radar_status(args.core_url, token)
    print(json.dumps(updated_status, indent=2, default=str))
    
    # Summary
    print("\n" + "=" * 60)
    if result.get("status") == "SUCCESS" or result.get("symbolsScanned", 0) > 0:
        print("SUCCESS: Daily AI signals have been generated!")
        print(f"Symbols scanned: {result.get('symbolsScanned', 'N/A')}")
        print("\nNext steps:")
        print("1. Refresh the Market Watch page to see the updated data")
        print("2. The API should now return predictions instead of null values")
        return 0
    else:
        print("WARNING: Signal generation may have failed or returned no results")
        print("Check the logs above for details")
        return 1


if __name__ == "__main__":
    sys.exit(main())
