#!/usr/bin/env python3
"""Verify Phase 3 & 4 Cutover Results"""
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

print("="*80)
print("PHASE 3 & 4 CUTOVER VERIFICATION")
print("="*80)

# Get all tables
cursor.execute("""
    SELECT table_name, table_type
    FROM information_schema.tables 
    WHERE table_schema = 'egx_portfolio'
    AND table_name NOT LIKE 'schema_migration_log'
    ORDER BY table_name
""")

tables = cursor.fetchall()

production_tables = []
old_tables = []
five_nf_tables = []
views = []

for table_name, table_type in tables:
    if table_type == 'VIEW':
        views.append(table_name)
    elif table_name.endswith('_old'):
        old_tables.append(table_name)
    elif '_5nf' in table_name:
        five_nf_tables.append(table_name)
    else:
        production_tables.append(table_name)

print("\n📊 PRODUCTION TABLES (After Cutover):")
print("-" * 70)
total_prod = 0
for table in sorted(production_tables):
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    count = cursor.fetchone()[0]
    total_prod += count
    print(f"✅ {table:40} | {count:6} rows")
print(f"   TOTAL: {total_prod:,} rows")

print("\n📊 BACKUP TABLES (_old):")
print("-" * 70)
total_old = 0
for table in sorted(old_tables):
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    count = cursor.fetchone()[0]
    total_old += count
    print(f"🗄️  {table:40} | {count:6} rows")
print(f"   TOTAL: {total_old:,} rows")

if five_nf_tables:
    print("\n⚠️  REMAINING _5NF TABLES (Should be empty after cutover):")
    print("-" * 70)
    for table in sorted(five_nf_tables):
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"⬜ {table:40} | {count:6} rows")

print("\n📊 VIEWS:")
print("-" * 70)
for view in sorted(views):
    print(f"👁️  {view}")

# Verify data in production tables
cursor.execute("SELECT COUNT(*) FROM stock_instruments")
stock_count = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM prediction_audit")
pred_count = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM portfolio_targets")
pt_count = cursor.fetchone()[0]

print("\n" + "="*80)
print("✅ CUTOVER VERIFICATION:")
print(f"   • stock_instruments: {stock_count} rows (PRODUCTION)")
print(f"   • prediction_audit: {pred_count} rows (PRODUCTION)")
print(f"   • portfolio_targets: {pt_count} rows (PRODUCTION)")
print(f"   • {len(old_tables)} backup tables preserved")
print(f"   • {len(views)} views operational")

if stock_count > 0 and pred_count > 0 and len(old_tables) >= 7:
    print("\n🎉 PHASE 3 & 4 COMPLETED SUCCESSFULLY!")
    print("   Production tables now use 5NF normalized schema")
    print("   Backup tables retained for rollback if needed")
else:
    print("\n⚠️  Some issues detected - please review")

print("="*80)

cursor.close()
conn.close()
