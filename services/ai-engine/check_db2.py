#!/usr/bin/env python3
"""Check database state for daily signals and market data."""
import mysql.connector

conn = mysql.connector.connect(
    host="127.0.0.1",
    port=3307,
    user="egx_app_user",
    password="EGX_App_7wN!9Qx2#M4Lz8",
    database="egx_portfolio",
)
cursor = conn.cursor()

# Check daily_ai_signals
cursor.execute("SELECT COUNT(*) FROM daily_ai_signals WHERE signal_date = CURDATE()")
count = cursor.fetchone()[0]
print(f"Today signals count: {count}")

cursor.execute("SELECT symbol, action, confidence_score, signal_date FROM daily_ai_signals ORDER BY signal_date DESC, symbol LIMIT 10")
rows = cursor.fetchall()
print("Recent signals:")
for r in rows:
    print(f"  {r}")

# Check market_daily_bars
cursor.execute("SELECT COUNT(*) FROM market_daily_bars")
mkt_count = cursor.fetchone()[0]
print(f"\nTotal market_daily_bars rows: {mkt_count}")

cursor.execute("SELECT MAX(trade_date) FROM market_daily_bars")
max_date = cursor.fetchone()[0]
print(f"Max trade_date: {max_date}")

cursor.execute("DESCRIBE market_daily_bars")
cols = cursor.fetchall()
print(f"market_daily_bars columns: {[c[0] for c in cols]}")

cursor.execute("SELECT COUNT(DISTINCT stock_id) FROM market_daily_bars")
sym_count = cursor.fetchone()[0]
print(f"Distinct stock_ids: {sym_count}")

# Check stock_instruments
cursor.execute("SELECT COUNT(*) FROM stock_instruments")
inst_count = cursor.fetchone()[0]
print(f"\nTotal instruments: {inst_count}")

conn.close()
