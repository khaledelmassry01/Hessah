#!/usr/bin/env python3
"""Fix the view with correct column name"""
import mysql.connector

DB_CONFIG = {
    "host": "localhost",
    "port": 3307,
    "user": "root",
    "password": "EGX_Root_9rT!5Vy3#K2Nq7",
    "database": "egx_portfolio"
}

conn = mysql.connector.connect(**DB_CONFIG)
cursor = conn.cursor()

# Check portfolio_runs columns
print("Checking portfolio_runs columns...")
cursor.execute("DESCRIBE portfolio_runs")
for row in cursor.fetchall():
    print(f"  {row[0]}")

# Drop and recreate view
cursor.execute("DROP VIEW IF EXISTS v_portfolio_targets_enhanced")

# Create view without the problematic column
cursor.execute("""
    CREATE VIEW v_portfolio_targets_enhanced AS
    SELECT 
        pt.id,
        pt.portfolio_run_id,
        pt.stock_id,
        pt.target_weight,
        pt.target_amount_egp,
        pt.sector_code,
        pt.constraint_flags_json,
        si.symbol,
        si.name as stock_name,
        sr.name as sector_name,
        (pt.target_weight * 100000) as calc_sample_amount_egp
    FROM portfolio_targets_5nf pt
    JOIN stock_instruments_5nf si ON pt.stock_id = si.id
    JOIN sector_reference_5nf sr ON si.sector_code = sr.code
""")

print("✅ Fixed v_portfolio_targets_enhanced view")

conn.commit()
cursor.close()
conn.close()
