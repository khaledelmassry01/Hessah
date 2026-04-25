#!/usr/bin/env python3
"""
Verify 5NF Migration Results
"""

import mysql.connector

DB_CONFIG = {
    "host": "localhost",
    "port": 3307,
    "user": "root",
    "password": "EGX_Root_9rT!5Vy3#K2Nq7",
    "database": "egx_portfolio"
}

def check_table(conn, table_name):
    """Check if table exists and get row count"""
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        return count
    except Exception as e:
        return f"ERROR: {e}"
    finally:
        cursor.close()

def check_view(conn, view_name):
    """Check if view exists"""
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT 1 FROM {view_name} LIMIT 1")
        cursor.fetchone()
        return "EXISTS"
    except Exception as e:
        return f"ERROR: {e}"
    finally:
        cursor.close()

def main():
    conn = mysql.connector.connect(**DB_CONFIG)
    
    print("="*80)
    print("5NF MIGRATION VERIFICATION REPORT")
    print("="*80)
    
    # Check new 5NF tables
    tables = [
        'schema_migration_log',
        'sector_reference_5nf',
        'stock_instruments_5nf',
        'daily_ai_signals_5nf',
        'signal_predictions',
        'signal_auxiliary_metrics',
        'signal_xai_reasons',
        'prediction_audit_5nf',
        'allocation_executions_5nf',
        'portfolio_targets_5nf',
        'model_training_sessions_5nf',
        'model_metrics',
        'model_hyperparameters',
        'model_feature_importance'
    ]
    
    print("\n📊 New 5NF Tables:")
    print("-" * 60)
    for table in tables:
        count = check_table(conn, table)
        status = "✅" if isinstance(count, int) else "❌"
        print(f"{status} {table:40} | Rows: {count}")
    
    # Check views
    views = [
        'v_prediction_audit_with_metrics',
        'v_allocation_executions_with_calculations',
        'v_portfolio_targets_enhanced'
    ]
    
    print("\n📊 Views:")
    print("-" * 60)
    for view in views:
        result = check_view(conn, view)
        status = "✅ EXISTS" if result == "EXISTS" else f"❌ {result}"
        print(f"{view:40} | {status}")
    
    # Check original tables (should still exist)
    print("\n📊 Original Tables (Verification - Should Still Exist):")
    print("-" * 60)
    original_tables = [
        'stock_instruments',
        'daily_ai_signals',
        'prediction_audit',
        'allocation_executions',
        'portfolio_targets',
        'model_performance_logs'
    ]
    
    for table in original_tables:
        count = check_table(conn, table)
        status = "✅" if isinstance(count, int) else "❌"
        print(f"{status} {table:40} | Rows: {count}")
    
    # Migration log summary
    print("\n📊 Migration Log Summary:")
    print("-" * 60)
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT phase, table_name, operation, rows_affected, status
            FROM schema_migration_log
            ORDER BY id DESC
            LIMIT 20
        """)
        rows = cursor.fetchall()
        for row in rows:
            status_icon = "✅" if row['status'] == 'COMPLETED' else "❌"
            print(f"{status_icon} {row['phase']}: {row['table_name']} | {row['operation']} | Rows: {row['rows_affected']}")
    except Exception as e:
        print(f"Could not read migration log: {e}")
    finally:
        cursor.close()
    
    print("\n" + "="*80)
    conn.close()

if __name__ == "__main__":
    main()
