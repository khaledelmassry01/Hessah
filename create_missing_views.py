#!/usr/bin/env python3
"""Create the missing views that failed verification"""
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

print("Creating missing views...")

# View 1: Prediction audit with metrics
cursor.execute("DROP VIEW IF EXISTS v_prediction_audit_with_metrics")
cursor.execute("""
    CREATE VIEW v_prediction_audit_with_metrics AS
    SELECT 
        p.*,
        m.close_price as reference_price,
        ((m.close_price - LAG(m.close_price) OVER (PARTITION BY p.stock_id ORDER BY m.trade_date)) / 
            NULLIF(LAG(m.close_price) OVER (PARTITION BY p.stock_id ORDER BY m.trade_date), 0)) as calc_actual_return_5d,
        ABS(p.predicted_return_5d - 
            ((m.close_price - LAG(m.close_price) OVER (PARTITION BY p.stock_id ORDER BY m.trade_date)) / 
             NULLIF(LAG(m.close_price) OVER (PARTITION BY p.stock_id ORDER BY m.trade_date), 0))
        ) as calc_error_abs
    FROM prediction_audit_5nf p
    LEFT JOIN market_daily_bars m ON p.stock_id = m.stock_id AND p.as_of_date = m.trade_date
""")
print("✅ Created v_prediction_audit_with_metrics")

# View 2: Allocation executions with calculations
cursor.execute("DROP VIEW IF EXISTS v_allocation_executions_with_calculations")
cursor.execute("""
    CREATE VIEW v_allocation_executions_with_calculations AS
    SELECT 
        ae.*,
        (ae.executed_shares * ae.price_snapshot) as calc_executed_amount_egp,
        (ae.target_amount_egp - (ae.executed_shares * ae.price_snapshot)) as calc_residual_component_egp
    FROM allocation_executions_5nf ae
""")
print("✅ Created v_allocation_executions_with_calculations")

conn.commit()
cursor.close()
conn.close()
print("\nAll missing views created!")
