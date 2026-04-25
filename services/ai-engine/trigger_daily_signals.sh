#!/bin/bash
# Trigger Daily AI Signal Generation for Market Watch (Linux/Mac)
# This script uses curl to trigger the admin radar scan endpoint

set -e

# Configuration - modify these if needed
CORE_URL="${CORE_URL:-http://localhost:8080}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${ADMIN_PASS:-admin123}"

echo "============================================"
echo "Daily AI Signal Generator - Market Watch"
echo "============================================"
echo ""
echo "RELAXED THRESHOLDS (Demo Mode):"
echo "  - SMART_MIN_CONFIDENCE: 0.35 (was 0.50)"
echo "  - Smart-money penalty: DISABLED"
echo "  - Dynamic thresholds: LOW=0.30, MEDIUM=0.40, HIGH=0.50"
echo ""
echo "Core backend: $CORE_URL"
echo ""

# Step 1: Check radar status before
echo "Checking current radar status..."
if ! curl -s -X POST "$CORE_URL/api/core/admin/radar/status" -H "Content-Type: application/json" 2>/dev/null; then
    echo "WARNING: Could not connect to core-backend. Is it running?"
    echo "Make sure the core-backend service is started on $CORE_URL"
    exit 1
fi
echo ""
echo ""

# Step 2: Trigger the radar scan
echo "Triggering admin radar scan..."
echo "This will populate the daily_ai_signals table with today's predictions."
echo ""

if curl -s -X POST "$CORE_URL/api/core/admin/radar/trigger" -H "Content-Type: application/json" 2>/dev/null; then
    echo ""
    echo "SUCCESS: Radar scan triggered!"
    echo "The daily AI signals are being generated."
else
    echo "ERROR: Radar trigger failed. Make sure you have ADMIN role access."
    echo ""
    echo "Alternative: Direct AI engine prediction"
    echo "You can also try calling the AI engine directly at http://localhost:8000/predict"
fi

echo ""
echo "============================================"
echo "Next steps:"
echo "1. Wait 10-30 seconds for the scan to complete"
echo "2. Refresh the Market Watch page"
echo "3. The API should now return predictions instead of null"
echo "============================================"
echo ""
