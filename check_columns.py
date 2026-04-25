#!/usr/bin/env python3
"""Check actual column names in tables"""
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

tables = ['stock_instruments', 'sector_reference', 'portfolio_targets', 
          'allocation_executions', 'model_performance_logs', 'daily_ai_signals']

for table in tables:
    print(f"\n{'='*60}")
    print(f"Table: {table}")
    print(f"{'='*60}")
    try:
        cursor.execute(f"DESCRIBE {table}")
        for row in cursor.fetchall():
            print(f"  {row[0]:20} | {row[1]:20} | {row[2]:10} | {row[3]:10}")
    except Exception as e:
        print(f"  ERROR: {e}")

conn.close()
