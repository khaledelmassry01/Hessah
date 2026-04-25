#!/usr/bin/env python3
"""
Fix 5NF Migration - Corrected Column Names
"""

import mysql.connector
from mysql.connector import Error

DB_CONFIG = {
    "host": "localhost",
    "port": 3307,
    "user": "root",
    "password": "EGX_Root_9rT!5Vy3#K2Nq7",
    "database": "egx_portfolio",
    "autocommit": False
}

def connect():
    return mysql.connector.connect(**DB_CONFIG)

def fix_sector_migration():
    """Fix sector migration with correct columns"""
    print("\n🔧 Fixing Sector Migration...")
    conn = connect()
    cursor = conn.cursor()
    
    try:
        # Copy from existing sector_reference (which has correct columns)
        cursor.execute("""
            INSERT IGNORE INTO sector_reference_5nf (code, name, description, created_at)
            SELECT code, name, NULL, created_at
            FROM sector_reference
        """)
        conn.commit()
        
        # Also add any sectors from stock_instruments that aren't in sector_reference
        cursor.execute("""
            INSERT IGNORE INTO sector_reference_5nf (code, name, created_at)
            SELECT DISTINCT sector_code, sector_code, NOW()
            FROM stock_instruments
            WHERE sector_code NOT IN (SELECT code FROM sector_reference)
        """)
        conn.commit()
        
        cursor.execute("SELECT COUNT(*) FROM sector_reference_5nf")
        count = cursor.fetchone()[0]
        print(f"   ✅ sector_reference_5nf now has {count} rows")
        
    except Error as e:
        print(f"   ❌ Error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def fix_stock_instruments_migration():
    """Fix stock_instruments with correct columns"""
    print("\n🔧 Fixing Stock Instruments Migration...")
    conn = connect()
    cursor = conn.cursor()
    
    try:
        # Drop and recreate with correct columns
        cursor.execute("DROP TABLE IF EXISTS stock_instruments_5nf")
        
        cursor.execute("""
            CREATE TABLE stock_instruments_5nf (
                id BIGINT PRIMARY KEY,
                symbol VARCHAR(16) NOT NULL UNIQUE,
                isin VARCHAR(32),
                name VARCHAR(255) NOT NULL,
                sector_code VARCHAR(64) NOT NULL,
                last_price DECIMAL(19,4),
                is_suspended TINYINT(1) NOT NULL DEFAULT 0,
                suspension_reason VARCHAR(255),
                created_at DATETIME(6) NOT NULL,
                updated_at DATETIME(6) NOT NULL,
                
                INDEX idx_sector (sector_code),
                CONSTRAINT fk_stock_sector_5nf 
                    FOREIGN KEY (sector_code) REFERENCES sector_reference_5nf(code)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """)
        
        # Migrate data
        cursor.execute("""
            INSERT INTO stock_instruments_5nf 
            (id, symbol, isin, name, sector_code, last_price, is_suspended, suspension_reason, created_at, updated_at)
            SELECT id, symbol, isin, name, sector_code, last_price, is_suspended, suspension_reason, created_at, updated_at
            FROM stock_instruments
        """)
        conn.commit()
        
        cursor.execute("SELECT COUNT(*) FROM stock_instruments_5nf")
        count = cursor.fetchone()[0]
        print(f"   ✅ stock_instruments_5nf now has {count} rows")
        
    except Error as e:
        print(f"   ❌ Error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def fix_portfolio_targets_migration():
    """Fix portfolio_targets with correct columns"""
    print("\n🔧 Fixing Portfolio Targets Migration...")
    conn = connect()
    cursor = conn.cursor()
    
    try:
        # Drop and recreate with correct columns
        cursor.execute("DROP TABLE IF EXISTS portfolio_targets_5nf")
        
        cursor.execute("""
            CREATE TABLE portfolio_targets_5nf (
                id BIGINT PRIMARY KEY,
                portfolio_run_id BIGINT NOT NULL,
                stock_id BIGINT NOT NULL,
                target_weight DECIMAL(10,8) NOT NULL,
                target_amount_egp DECIMAL(19,4) NOT NULL,
                sector_code VARCHAR(64) NOT NULL,  -- Keep for now (will be removed in full 5NF)
                constraint_flags_json JSON,
                
                UNIQUE KEY uq_portfolio_targets_run_stock (portfolio_run_id, stock_id),
                INDEX idx_portfolio_run (portfolio_run_id),
                INDEX idx_stock (stock_id),
                CONSTRAINT fk_portfolio_targets_run_5nf 
                    FOREIGN KEY (portfolio_run_id) REFERENCES portfolio_runs(id),
                CONSTRAINT fk_portfolio_targets_stock_5nf 
                    FOREIGN KEY (stock_id) REFERENCES stock_instruments_5nf(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """)
        
        # Migrate data
        cursor.execute("""
            INSERT INTO portfolio_targets_5nf 
            (id, portfolio_run_id, stock_id, target_weight, target_amount_egp, sector_code, constraint_flags_json)
            SELECT id, portfolio_run_id, stock_id, target_weight, target_amount_egp, sector_code, constraint_flags_json
            FROM portfolio_targets
        """)
        conn.commit()
        
        cursor.execute("SELECT COUNT(*) FROM portfolio_targets_5nf")
        count = cursor.fetchone()[0]
        print(f"   ✅ portfolio_targets_5nf now has {count} rows")
        
    except Error as e:
        print(f"   ❌ Error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def fix_allocation_executions_migration():
    """Fix allocation_executions with correct columns"""
    print("\n🔧 Fixing Allocation Executions Migration...")
    conn = connect()
    cursor = conn.cursor()
    
    try:
        # Drop and recreate with correct columns
        cursor.execute("DROP TABLE IF EXISTS allocation_executions_5nf")
        
        cursor.execute("""
            CREATE TABLE allocation_executions_5nf (
                id BIGINT PRIMARY KEY,
                portfolio_run_id BIGINT NOT NULL,
                stock_id BIGINT NOT NULL,
                price_snapshot DECIMAL(19,4) NOT NULL,
                target_amount_egp DECIMAL(19,4) NOT NULL,
                executed_shares BIGINT NOT NULL DEFAULT 0,
                executed_amount_egp DECIMAL(19,4) NOT NULL DEFAULT 0.0000,
                residual_component_egp DECIMAL(19,4) NOT NULL DEFAULT 0.0000,
                settlement_date DATE,
                settlement_status ENUM('CLEARED','FAILED','PENDING') NOT NULL DEFAULT 'PENDING',
                created_at DATETIME(6) NOT NULL,
                
                INDEX idx_portfolio_run (portfolio_run_id),
                INDEX idx_stock (stock_id),
                INDEX idx_settlement_status (settlement_status),
                CONSTRAINT fk_alloc_exec_run_5nf 
                    FOREIGN KEY (portfolio_run_id) REFERENCES portfolio_runs(id),
                CONSTRAINT fk_alloc_exec_stock_5nf 
                    FOREIGN KEY (stock_id) REFERENCES stock_instruments_5nf(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """)
        
        # Migrate data
        cursor.execute("""
            INSERT INTO allocation_executions_5nf 
            (id, portfolio_run_id, stock_id, price_snapshot, target_amount_egp, 
             executed_shares, executed_amount_egp, residual_component_egp,
             settlement_date, settlement_status, created_at)
            SELECT id, portfolio_run_id, stock_id, price_snapshot, target_amount_egp,
                   executed_shares, executed_amount_egp, residual_component_egp,
                   settlement_date, settlement_status, created_at
            FROM allocation_executions
        """)
        conn.commit()
        
        cursor.execute("SELECT COUNT(*) FROM allocation_executions_5nf")
        count = cursor.fetchone()[0]
        print(f"   ✅ allocation_executions_5nf now has {count} rows")
        
    except Error as e:
        print(f"   ❌ Error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def fix_model_tables():
    """Fix model tables with correct schema"""
    print("\n🔧 Fixing Model Tables Migration...")
    conn = connect()
    cursor = conn.cursor()
    
    try:
        # Drop and recreate with correct columns matching actual schema
        cursor.execute("DROP TABLE IF EXISTS model_performance_logs_5nf")
        
        cursor.execute("""
            CREATE TABLE model_performance_logs_5nf (
                id BIGINT PRIMARY KEY,
                request_id VARCHAR(64),
                user_id BIGINT,
                risk_level VARCHAR(16) NOT NULL,
                model_version VARCHAR(64) NOT NULL,
                historical_date DATE NOT NULL,
                evaluation_date DATE NOT NULL,
                horizon_days INT NOT NULL,
                budget_egp DECIMAL(19,4) NOT NULL,
                predicted_return DECIMAL(12,8) NOT NULL,
                actual_return DECIMAL(12,8) NOT NULL,
                prediction_error DECIMAL(12,8) NOT NULL,
                risk_free_rate DECIMAL(8,6) NOT NULL,
                covariance_shrinkage DECIMAL(8,6) NOT NULL,
                run_status VARCHAR(16) NOT NULL,
                created_at DATETIME(6) NOT NULL,
                
                INDEX idx_user_id (user_id),
                INDEX idx_risk_level (risk_level),
                INDEX idx_model_version (model_version),
                INDEX idx_historical_date (historical_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """)
        
        # Migrate data
        cursor.execute("""
            INSERT INTO model_performance_logs_5nf 
            (id, request_id, user_id, risk_level, model_version, historical_date, evaluation_date,
             horizon_days, budget_egp, predicted_return, actual_return, prediction_error,
             risk_free_rate, covariance_shrinkage, run_status, created_at)
            SELECT id, request_id, user_id, risk_level, model_version, historical_date, evaluation_date,
                   horizon_days, budget_egp, predicted_return, actual_return, prediction_error,
                   risk_free_rate, covariance_shrinkage, run_status, created_at
            FROM model_performance_logs
        """)
        conn.commit()
        
        cursor.execute("SELECT COUNT(*) FROM model_performance_logs_5nf")
        count = cursor.fetchone()[0]
        print(f"   ✅ model_performance_logs_5nf now has {count} rows")
        
        # Also create decomposed tables for 5NF
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS model_risk_levels (
                risk_level VARCHAR(16) PRIMARY KEY,
                description VARCHAR(255),
                max_allocation_pct DECIMAL(5,2),
                created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """)
        
        cursor.execute("""
            INSERT IGNORE INTO model_risk_levels (risk_level, description)
            SELECT DISTINCT risk_level, CONCAT(risk_level, ' Risk Profile')
            FROM model_performance_logs
        """)
        conn.commit()
        
    except Error as e:
        print(f"   ❌ Error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def fix_daily_ai_signals_migration():
    """Fix daily_ai_signals with correct columns"""
    print("\n🔧 Fixing Daily AI Signals Migration...")
    conn = connect()
    cursor = conn.cursor()
    
    try:
        # Drop and recreate with correct columns
        cursor.execute("DROP TABLE IF EXISTS daily_ai_signals_5nf")
        
        cursor.execute("""
            CREATE TABLE daily_ai_signals_5nf (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                symbol VARCHAR(16) NOT NULL,
                stock_id BIGINT,
                signal_date DATE NOT NULL,
                action VARCHAR(20) NOT NULL,
                confidence_score DECIMAL(6,4),
                model_version VARCHAR(64),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                
                UNIQUE KEY uq_daily_ai_signals_symbol_date (symbol, signal_date),
                INDEX idx_signal_date (signal_date),
                INDEX idx_symbol (symbol),
                CONSTRAINT fk_daily_ai_signals_stock_5nf 
                    FOREIGN KEY (stock_id) REFERENCES stock_instruments_5nf(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """)
        
        # Migrate only if there is data
        cursor.execute("SELECT COUNT(*) FROM daily_ai_signals")
        count = cursor.fetchone()[0]
        
        if count > 0:
            cursor.execute("""
                INSERT INTO daily_ai_signals_5nf 
                (symbol, stock_id, signal_date, action, confidence_score, model_version, created_at, updated_at)
                SELECT symbol, stock_id, signal_date, action, confidence_score, model_version, created_at, updated_at
                FROM daily_ai_signals
            """)
            
            # Migrate predictions
            cursor.execute("""
                INSERT INTO signal_predictions (signal_id, prediction_type, predicted_value, confidence)
                SELECT s.id, 'RETURN_5D', das.predicted_return_5d, das.confidence_score
                FROM daily_ai_signals das
                JOIN daily_ai_signals_5nf s 
                    ON das.symbol = s.symbol AND das.signal_date = s.signal_date
                WHERE das.predicted_return_5d IS NOT NULL
            """)
            
            # Migrate auxiliary metrics
            cursor.execute("""
                INSERT INTO signal_auxiliary_metrics (signal_id, metric_type, metric_value)
                SELECT s.id, 'SMART_MONEY', das.smart_money_signal
                FROM daily_ai_signals das
                JOIN daily_ai_signals_5nf s 
                    ON das.symbol = s.symbol AND das.signal_date = s.signal_date
                WHERE das.smart_money_signal IS NOT NULL
            """)
            
            cursor.execute("""
                INSERT INTO signal_auxiliary_metrics (signal_id, metric_type, metric_value)
                SELECT s.id, 'MARKET_SENTIMENT', das.market_sentiment_score
                FROM daily_ai_signals das
                JOIN daily_ai_signals_5nf s 
                    ON das.symbol = s.symbol AND das.signal_date = s.signal_date
                WHERE das.market_sentiment_score IS NOT NULL
            """)
            
            cursor.execute("""
                INSERT INTO signal_auxiliary_metrics (signal_id, metric_type, metric_value)
                SELECT s.id, 'RETURN_ANNUAL', das.expected_return_annual
                FROM daily_ai_signals das
                JOIN daily_ai_signals_5nf s 
                    ON das.symbol = s.symbol AND das.signal_date = s.signal_date
                WHERE das.expected_return_annual IS NOT NULL
            """)
            
            cursor.execute("""
                INSERT INTO signal_auxiliary_metrics (signal_id, metric_type, metric_value)
                SELECT s.id, 'VOLATILITY', das.expected_volatility
                FROM daily_ai_signals das
                JOIN daily_ai_signals_5nf s 
                    ON das.symbol = s.symbol AND das.signal_date = s.signal_date
                WHERE das.expected_volatility IS NOT NULL
            """)
            
            conn.commit()
            print(f"   ✅ daily_ai_signals_5nf now has {count} rows with decomposed data")
        else:
            print(f"   ⚠️ No data in daily_ai_signals to migrate")
        
    except Error as e:
        print(f"   ❌ Error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def recreate_views():
    """Recreate views with corrected definitions"""
    print("\n🔧 Recreating Views...")
    conn = connect()
    cursor = conn.cursor()
    
    try:
        # Fix portfolio targets view
        cursor.execute("DROP VIEW IF EXISTS v_portfolio_targets_enhanced")
        
        cursor.execute("""
            CREATE VIEW v_portfolio_targets_enhanced AS
            SELECT 
                pt.*,
                si.symbol,
                si.name as stock_name,
                sr.code as sector_code,
                sr.name as sector_name
            FROM portfolio_targets_5nf pt
            JOIN stock_instruments_5nf si ON pt.stock_id = si.id
            JOIN sector_reference_5nf sr ON si.sector_code = sr.code
        """)
        print("   ✅ v_portfolio_targets_enhanced created")
        
        # Update allocation view to use correct table
        cursor.execute("DROP VIEW IF EXISTS v_allocation_executions_with_calculations")
        
        cursor.execute("""
            CREATE VIEW v_allocation_executions_with_calculations AS
            SELECT 
                ae.*,
                (ae.executed_shares * ae.price_snapshot) as calc_executed_amount_egp,
                (ae.target_amount_egp - (ae.executed_shares * ae.price_snapshot)) as calc_residual_component_egp
            FROM allocation_executions_5nf ae
        """)
        print("   ✅ v_allocation_executions_with_calculations created")
        
        conn.commit()
        
    except Error as e:
        print(f"   ❌ Error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def final_verification():
    """Final verification of all migrations"""
    print("\n" + "="*80)
    print("FINAL VERIFICATION")
    print("="*80)
    
    conn = connect()
    cursor = conn.cursor()
    
    tables = [
        ('sector_reference_5nf', 'Normalized sectors'),
        ('stock_instruments_5nf', 'Normalized stocks'),
        ('daily_ai_signals_5nf', 'AI signals core'),
        ('signal_predictions', 'Decomposed predictions'),
        ('signal_auxiliary_metrics', 'Decomposed metrics'),
        ('signal_xai_reasons', 'XAI reasons'),
        ('prediction_audit_5nf', 'Predictions without calc cols'),
        ('allocation_executions_5nf', 'Allocations with calc cols'),
        ('portfolio_targets_5nf', 'Portfolio targets'),
        ('model_performance_logs_5nf', 'Model performance'),
        ('model_risk_levels', 'Risk level reference'),
    ]
    
    total_rows = 0
    for table, desc in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            total_rows += count
            print(f"✅ {table:40} | {count:6} rows | {desc}")
        except Exception as e:
            print(f"❌ {table:40} | ERROR: {e}")
    
    print("-" * 80)
    print(f"📊 TOTAL ROWS MIGRATED: {total_rows}")
    print("="*80)
    
    cursor.close()
    conn.close()

def main():
    print("="*80)
    print("5NF MIGRATION FIX - Correcting Column Names")
    print("="*80)
    
    fix_sector_migration()
    fix_stock_instruments_migration()
    fix_daily_ai_signals_migration()
    fix_prediction_audit()  # Add this function
    fix_portfolio_targets_migration()
    fix_allocation_executions_migration()
    fix_model_tables()
    recreate_views()
    final_verification()
    
    print("\n" + "="*80)
    print("✅ ALL FIXES COMPLETED")
    print("="*80)

def fix_prediction_audit():
    """Fix prediction_audit if needed"""
    print("\n🔧 Checking Prediction Audit...")
    conn = connect()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT COUNT(*) FROM prediction_audit_5nf")
        count = cursor.fetchone()[0]
        print(f"   ✅ prediction_audit_5nf already has {count} rows")
    except Error as e:
        print(f"   ⚠️ {e}")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    main()
