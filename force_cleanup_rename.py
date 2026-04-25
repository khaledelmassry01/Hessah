#!/usr/bin/env python3
"""
FORCE CLEANUP & RENAME - 5NF Tables to Production
Execute exact SQL sequence to clean messy state
"""

import mysql.connector
from mysql.connector import Error

DB_CONFIG = {
    "host": "localhost",
    "port": 3307,
    "user": "root",
    "password": "EGX_Root_9rT!5Vy3#K2Nq7",
    "database": "egx_portfolio"
}

print("="*80)
print("FORCE CLEANUP & RENAME - 5NF MIGRATION FINALIZATION")
print("="*80)

conn = mysql.connector.connect(**DB_CONFIG)
cursor = conn.cursor()

# Execute exact SQL sequence as specified
sql_commands = [
    "SET FOREIGN_KEY_CHECKS=0",
    
    # 1. Drop all backup/old tables
    "DROP TABLE IF EXISTS stock_instruments_old",
    "DROP TABLE IF EXISTS sector_reference_old",
    "DROP TABLE IF EXISTS prediction_audit_old",
    "DROP TABLE IF EXISTS allocation_executions_old",
    "DROP TABLE IF EXISTS portfolio_targets_old",
    "DROP TABLE IF EXISTS model_performance_logs_old",
    "DROP TABLE IF EXISTS daily_ai_signals_old",
    
    # 2. Drop the redundant base tables (so the 5nf ones can take their place)
    "DROP TABLE IF EXISTS stock_instruments",
    "DROP TABLE IF EXISTS sector_reference",
    "DROP TABLE IF EXISTS prediction_audit",
    "DROP TABLE IF EXISTS allocation_executions",
    "DROP TABLE IF EXISTS portfolio_targets",
    "DROP TABLE IF EXISTS model_performance_logs",
    "DROP TABLE IF EXISTS daily_ai_signals",
    
    # 3. Rename the _5nf tables to be the official production tables
    "RENAME TABLE stock_instruments_5nf TO stock_instruments",
    "RENAME TABLE sector_reference_5nf TO sector_reference",
    "RENAME TABLE prediction_audit_5nf TO prediction_audit",
    "RENAME TABLE allocation_executions_5nf TO allocation_executions",
    "RENAME TABLE portfolio_targets_5nf TO portfolio_targets",
    "RENAME TABLE model_performance_logs_5nf TO model_performance_logs",
    "RENAME TABLE daily_ai_signals_5nf TO daily_ai_signals",
    
    "SET FOREIGN_KEY_CHECKS=1"
]

print("\nExecuting cleanup sequence...")
print("-" * 80)

try:
    for sql in sql_commands:
        print(f"   Executing: {sql[:60]}...")
        cursor.execute(sql)
        conn.commit()
    
    print("-" * 80)
    print("✅ Cleanup sequence completed successfully")
    
except Error as e:
    print(f"\n❌ ERROR: {e}")
    conn.rollback()
    raise

# Verify final state
print("\n" + "="*80)
print("VERIFYING FINAL CLEAN STATE")
print("="*80)

cursor.execute("""
    SELECT table_name, table_type
    FROM information_schema.tables 
    WHERE table_schema = 'egx_portfolio'
    AND (table_name LIKE '%_old' OR table_name LIKE '%_5nf')
    ORDER BY table_name
""")

remaining = cursor.fetchall()

if remaining:
    print(f"\n⚠️  Remaining _old or _5nf tables ({len(remaining)}):")
    for table, ttype in remaining:
        print(f"   • {table} ({ttype})")
else:
    print("\n✅ NO _old OR _5nf TABLES REMAIN - DATABASE IS CLEAN")

# Show production tables
print("\n📊 PRODUCTION TABLES (Now Clean 5NF):")
print("-" * 80)

cursor.execute("""
    SELECT table_name
    FROM information_schema.tables 
    WHERE table_schema = 'egx_portfolio'
    AND table_name IN ('stock_instruments', 'sector_reference', 'prediction_audit',
                       'allocation_executions', 'portfolio_targets', 'model_performance_logs',
                       'daily_ai_signals')
    ORDER BY table_name
""")

for (table,) in cursor.fetchall():
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    count = cursor.fetchone()[0]
    print(f"✅ {table:40} | {count:6} rows")

cursor.close()
conn.close()

print("\n" + "="*80)
print("🎉 FORCE CLEANUP COMPLETE - DATABASE IS CLEAN AND NORMALIZED")
print("="*80)
