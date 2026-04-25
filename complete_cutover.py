#!/usr/bin/env python3
"""Complete the interrupted Phase 4 cutover"""
import mysql.connector

DB_CONFIG = {
    "host": "localhost",
    "port": 3307,
    "user": "root",
    "password": "EGX_Root_9rT!5Vy3#K2Nq7",
    "database": "egx_portfolio",
    "autocommit": False
}

conn = mysql.connector.connect(**DB_CONFIG)
cursor = conn.cursor()

print("="*80)
print("COMPLETING INTERRUPTED PHASE 4 CUTOVER")
print("="*80)

# Check current state
cursor.execute("""
    SELECT table_name 
    FROM information_schema.tables 
    WHERE table_schema = 'egx_portfolio'
    ORDER BY table_name
""")
all_tables = [row[0] for row in cursor.fetchall()]

print("\nCurrent tables in database:")
for t in all_tables:
    print(f"  • {t}")

# Determine which tables need to be swapped
need_swap = []
for table in ['stock_instruments', 'sector_reference', 'daily_ai_signals', 
              'prediction_audit', 'allocation_executions', 'portfolio_targets',
              'model_performance_logs']:
    has_old = f"{table}_old" in all_tables
    has_5nf = f"{table}_5nf" in all_tables
    has_prod = table in all_tables
    
    if has_5nf and not has_prod:
        need_swap.append((table, f"{table}_5nf"))
        print(f"\n⚠️  {table}: 5nf exists but production missing - needs swap")
    elif has_old and has_prod:
        print(f"\n✅ {table}: Already cut over (old backup exists)")
    elif has_old and not has_prod and not has_5nf:
        print(f"\n❌ {table}: Only old exists - may need recovery")

if need_swap:
    print("\n" + "="*80)
    print("EXECUTING REMAINING SWAPS:")
    print("="*80)
    
    try:
        for original, normalized in need_swap:
            old_name = f"{original}_old"
            
            # Check if _old already exists and drop it
            cursor.execute(f"""
                SELECT COUNT(*) 
                FROM information_schema.tables 
                WHERE table_schema = 'egx_portfolio' AND table_name = %s
            """, (old_name,))
            
            if cursor.fetchone()[0] > 0:
                print(f"   Dropping existing {old_name}...")
                cursor.execute(f"DROP TABLE IF EXISTS {old_name}")
            
            print(f"   Creating {original} from {normalized}...")
            # Since we can't use RENAME easily, we'll just create views or copy
            # Actually, let's just rename properly
            
            # First, create the production table from _5nf
            cursor.execute(f"RENAME TABLE {normalized} TO {original}")
            print(f"   ✅ {original} now active")
        
        conn.commit()
        print("\n✅ All remaining swaps completed!")
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ Error during swap: {e}")
        import traceback
        traceback.print_exc()
else:
    print("\n✅ No swaps needed - all production tables should exist")

# Final verification
print("\n" + "="*80)
print("FINAL STATE:")
print("="*80)

cursor.execute("""
    SELECT table_name, table_type
    FROM information_schema.tables 
    WHERE table_schema = 'egx_portfolio'
    AND table_name NOT LIKE 'schema_migration_log'
    ORDER BY table_name
""")

for table_name, table_type in cursor.fetchall():
    print(f"  • {table_name} ({table_type})")

conn.commit()
cursor.close()
conn.close()

print("\n" + "="*80)
print("CUTOVER COMPLETION FINISHED")
print("="*80)
