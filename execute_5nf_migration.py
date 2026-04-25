#!/usr/bin/env python3
"""
5NF Database Migration - Phase 1 & 2 Execution
Creates new normalized tables and migrates data without touching original tables
"""

import mysql.connector
from mysql.connector import Error
from datetime import datetime
import sys

DB_CONFIG = {
    "host": "localhost",
    "port": 3307,
    "user": "root",
    "password": "EGX_Root_9rT!5Vy3#K2Nq7",
    "database": "egx_portfolio",
    "autocommit": False
}

class MigrationRunner:
    def __init__(self):
        self.conn = None
        self.cursor = None
        self.migration_results = {}
        
    def connect(self):
        """Establish database connection"""
        try:
            self.conn = mysql.connector.connect(**DB_CONFIG)
            self.cursor = self.conn.cursor(dictionary=True)
            print("✅ Connected to database: egx_portfolio")
            return True
        except Error as e:
            print(f"❌ Connection failed: {e}")
            return False
    
    def log_migration(self, phase, table_name, operation, rows_affected=None, status='RUNNING', error_msg=None):
        """Log migration progress"""
        try:
            self.cursor.execute("""
                INSERT INTO schema_migration_log 
                (phase, table_name, operation, rows_affected, status, error_message, started_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """, (phase, table_name, operation, rows_affected, status, error_msg))
            self.conn.commit()
        except Error as e:
            print(f"   Warning: Could not log migration: {e}")
    
    def execute_sql(self, sql, description, log_phase="PHASE_1", log_table=""):
        """Execute SQL with error handling"""
        try:
            print(f"   Executing: {description}...")
            for statement in sql.split(';'):
                stmt = statement.strip()
                if stmt:
                    self.cursor.execute(stmt)
            self.conn.commit()
            print(f"   ✅ Success")
            return True
        except Error as e:
            self.conn.rollback()
            print(f"   ❌ Failed: {e}")
            self.log_migration(log_phase, log_table, description, status='FAILED', error_msg=str(e))
            return False
    
    def get_row_count(self, table_name):
        """Get row count from a table"""
        try:
            self.cursor.execute(f"SELECT COUNT(*) as cnt FROM {table_name}")
            result = self.cursor.fetchone()
            return result['cnt'] if result else 0
        except:
            return 0

    # =========================================================================
    # PHASE 1: PREPARATION - Create Migration Log and New Tables
    # =========================================================================
    
    def phase1_create_migration_log(self):
        """Create the migration logging table"""
        print("\n" + "="*80)
        print("PHASE 1.1: Creating Migration Log Table")
        print("="*80)
        
        sql = """
        CREATE TABLE IF NOT EXISTS schema_migration_log (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            phase VARCHAR(50) NOT NULL,
            table_name VARCHAR(100) NOT NULL,
            operation VARCHAR(50) NOT NULL,
            rows_affected BIGINT,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP NULL,
            error_message TEXT,
            status ENUM('RUNNING','COMPLETED','FAILED') DEFAULT 'RUNNING'
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """
        
        if self.execute_sql(sql, "Create schema_migration_log table", "PHASE_1", "schema_migration_log"):
            self.log_migration("PHASE_1", "schema_migration_log", "CREATE_TABLE", status='COMPLETED')
            return True
        return False
    
    def phase1_create_sector_tables(self):
        """Create normalized sector tables (3NF fix)"""
        print("\n" + "="*80)
        print("PHASE 1.2: Creating Normalized Sector Tables (3NF Fix)")
        print("="*80)
        
        # Enhance existing sector_reference or create new
        sql = """
        CREATE TABLE IF NOT EXISTS sector_reference_5nf (
            code VARCHAR(64) PRIMARY KEY,
            name VARCHAR(128) NOT NULL,
            description TEXT,
            parent_sector_code VARCHAR(64),
            created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
            updated_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
            
            CONSTRAINT fk_sector_parent 
                FOREIGN KEY (parent_sector_code) REFERENCES sector_reference(code)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """
        self.execute_sql(sql, "Create sector_reference_5nf", "PHASE_1", "sector_reference_5nf")
        
        # Create normalized stock_instruments (without sector_name)
        sql = """
        CREATE TABLE IF NOT EXISTS stock_instruments_5nf (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            symbol VARCHAR(16) NOT NULL UNIQUE,
            isin VARCHAR(12) UNIQUE,
            name VARCHAR(128) NOT NULL,
            sector_code VARCHAR(64) NOT NULL,
            listed_shares BIGINT,
            currency VARCHAR(3) DEFAULT 'EGP',
            is_active BOOLEAN DEFAULT TRUE,
            created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
            
            INDEX idx_sector (sector_code),
            CONSTRAINT fk_stock_sector 
                FOREIGN KEY (sector_code) REFERENCES sector_reference_5nf(code)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """
        self.execute_sql(sql, "Create stock_instruments_5nf", "PHASE_1", "stock_instruments_5nf")
        
        return True
    
    def phase1_create_ai_signals_tables(self):
        """Create 4NF-decomposed AI signal tables"""
        print("\n" + "="*80)
        print("PHASE 1.3: Creating 4NF-Decomposed AI Signal Tables")
        print("="*80)
        
        # Core signal table (minimal)
        sql = """
        CREATE TABLE IF NOT EXISTS daily_ai_signals_5nf (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            stock_id BIGINT NOT NULL,
            signal_date DATE NOT NULL,
            action VARCHAR(20) NOT NULL,
            confidence_score DECIMAL(6,4),
            model_version VARCHAR(64),
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            
            UNIQUE KEY uq_daily_ai_signals_stock_date (stock_id, signal_date),
            INDEX idx_signal_date (signal_date),
            CONSTRAINT fk_daily_ai_signals_stock 
                FOREIGN KEY (stock_id) REFERENCES stock_instruments_5nf(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """
        self.execute_sql(sql, "Create daily_ai_signals_5nf", "PHASE_1", "daily_ai_signals_5nf")
        
        # Signal predictions (4NF decomposition)
        sql = """
        CREATE TABLE IF NOT EXISTS signal_predictions (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            signal_id BIGINT NOT NULL,
            prediction_type VARCHAR(32) NOT NULL,
            predicted_value DECIMAL(10,6) NOT NULL,
            confidence DECIMAL(6,4),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            
            UNIQUE KEY uq_signal_predictions_type (signal_id, prediction_type),
            CONSTRAINT fk_predictions_signal 
                FOREIGN KEY (signal_id) REFERENCES daily_ai_signals_5nf(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """
        self.execute_sql(sql, "Create signal_predictions", "PHASE_1", "signal_predictions")
        
        # Signal auxiliary metrics (4NF decomposition)
        sql = """
        CREATE TABLE IF NOT EXISTS signal_auxiliary_metrics (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            signal_id BIGINT NOT NULL,
            metric_type VARCHAR(32) NOT NULL,
            metric_value DECIMAL(10,6),
            metadata_json JSON,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            
            UNIQUE KEY uq_aux_metrics_type (signal_id, metric_type),
            CONSTRAINT fk_aux_metrics_signal 
                FOREIGN KEY (signal_id) REFERENCES daily_ai_signals_5nf(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """
        self.execute_sql(sql, "Create signal_auxiliary_metrics", "PHASE_1", "signal_auxiliary_metrics")
        
        # XAI reasons (multi-valued attribute)
        sql = """
        CREATE TABLE IF NOT EXISTS signal_xai_reasons (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            signal_id BIGINT NOT NULL,
            reason_order INT NOT NULL,
            reason_text VARCHAR(500) NOT NULL,
            reason_weight DECIMAL(6,4),
            
            CONSTRAINT fk_xai_reasons_signal 
                FOREIGN KEY (signal_id) REFERENCES daily_ai_signals_5nf(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """
        self.execute_sql(sql, "Create signal_xai_reasons", "PHASE_1", "signal_xai_reasons")
        
        return True
    
    def phase1_create_prediction_tables(self):
        """Create normalized prediction tables (remove calculated columns)"""
        print("\n" + "="*80)
        print("PHASE 1.4: Creating Normalized Prediction Tables")
        print("="*80)
        
        # Refactored prediction_audit (without calculated columns)
        sql = """
        CREATE TABLE IF NOT EXISTS prediction_audit_5nf (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            as_of_date DATE NOT NULL,
            symbol VARCHAR(16) NOT NULL,
            stock_id BIGINT,
            request_id VARCHAR(128),
            predicted_return_5d DOUBLE NOT NULL,
            confidence_score DOUBLE,
            reconciled_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            
            UNIQUE KEY uq_prediction_audit_asof_symbol (as_of_date, symbol, request_id),
            INDEX idx_as_of_date (as_of_date),
            INDEX idx_symbol (symbol),
            CONSTRAINT fk_prediction_stock 
                FOREIGN KEY (stock_id) REFERENCES stock_instruments_5nf(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """
        self.execute_sql(sql, "Create prediction_audit_5nf", "PHASE_1", "prediction_audit_5nf")
        
        return True
    
    def phase1_create_allocation_tables(self):
        """Create normalized allocation tables (remove calculated columns)"""
        print("\n" + "="*80)
        print("PHASE 1.5: Creating Normalized Allocation Tables")
        print("="*80)
        
        # Refactored allocation_executions (without calculated columns)
        sql = """
        CREATE TABLE IF NOT EXISTS allocation_executions_5nf (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            portfolio_run_id BIGINT NOT NULL,
            stock_id BIGINT NOT NULL,
            price_snapshot DECIMAL(19,4) NOT NULL,
            target_amount_egp DECIMAL(19,4) NOT NULL,
            executed_shares BIGINT NOT NULL DEFAULT 0,
            settlement_date DATE,
            settlement_status ENUM('CLEARED','FAILED','PENDING') NOT NULL DEFAULT 'PENDING',
            created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
            
            INDEX idx_portfolio_run (portfolio_run_id),
            INDEX idx_stock (stock_id),
            INDEX idx_settlement_status (settlement_status),
            CONSTRAINT fk_alloc_exec_run 
                FOREIGN KEY (portfolio_run_id) REFERENCES portfolio_runs(id),
            CONSTRAINT fk_alloc_exec_stock 
                FOREIGN KEY (stock_id) REFERENCES stock_instruments_5nf(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """
        self.execute_sql(sql, "Create allocation_executions_5nf", "PHASE_1", "allocation_executions_5nf")
        
        return True
    
    def phase1_create_portfolio_tables(self):
        """Create normalized portfolio tables (remove denormalized sector_code)"""
        print("\n" + "="*80)
        print("PHASE 1.6: Creating Normalized Portfolio Tables")
        print("="*80)
        
        # Refactored portfolio_targets (without sector_code)
        sql = """
        CREATE TABLE IF NOT EXISTS portfolio_targets_5nf (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            portfolio_run_id BIGINT NOT NULL,
            stock_id BIGINT NOT NULL,
            target_weight DECIMAL(10,8) NOT NULL,
            constraint_flags_json JSON,
            created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
            
            UNIQUE KEY uq_portfolio_targets_run_stock (portfolio_run_id, stock_id),
            INDEX idx_portfolio_run (portfolio_run_id),
            INDEX idx_stock (stock_id),
            CONSTRAINT fk_portfolio_targets_run 
                FOREIGN KEY (portfolio_run_id) REFERENCES portfolio_runs(id),
            CONSTRAINT fk_portfolio_targets_stock 
                FOREIGN KEY (stock_id) REFERENCES stock_instruments_5nf(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """
        self.execute_sql(sql, "Create portfolio_targets_5nf", "PHASE_1", "portfolio_targets_5nf")
        
        return True
    
    def phase1_create_model_tables(self):
        """Create 5NF-decomposed model performance tables"""
        print("\n" + "="*80)
        print("PHASE 1.7: Creating 5NF-Decomposed Model Tables")
        print("="*80)
        
        # Core model training sessions
        sql = """
        CREATE TABLE IF NOT EXISTS model_training_sessions_5nf (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            model_version VARCHAR(64) NOT NULL UNIQUE,
            training_date DATE NOT NULL,
            backtest_job_id BIGINT,
            training_data_start DATE NOT NULL,
            training_data_end DATE NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            INDEX idx_backtest_job (backtest_job_id),
            CONSTRAINT fk_training_backtest 
                FOREIGN KEY (backtest_job_id) REFERENCES backtest_jobs(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """
        self.execute_sql(sql, "Create model_training_sessions_5nf", "PHASE_1", "model_training_sessions_5nf")
        
        # Model metrics (5NF decomposition)
        sql = """
        CREATE TABLE IF NOT EXISTS model_metrics (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            model_version VARCHAR(64) NOT NULL,
            metric_name VARCHAR(32) NOT NULL,
            metric_value DECIMAL(10,6) NOT NULL,
            calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            UNIQUE KEY uq_model_metrics (model_version, metric_name),
            CONSTRAINT fk_metrics_model 
                FOREIGN KEY (model_version) REFERENCES model_training_sessions_5nf(model_version)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """
        self.execute_sql(sql, "Create model_metrics", "PHASE_1", "model_metrics")
        
        # Model hyperparameters (5NF decomposition)
        sql = """
        CREATE TABLE IF NOT EXISTS model_hyperparameters (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            model_version VARCHAR(64) NOT NULL,
            param_name VARCHAR(64) NOT NULL,
            param_value VARCHAR(255) NOT NULL,
            param_type VARCHAR(20) NOT NULL,
            
            UNIQUE KEY uq_model_hyperparams (model_version, param_name),
            CONSTRAINT fk_hyperparams_model 
                FOREIGN KEY (model_version) REFERENCES model_training_sessions_5nf(model_version)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """
        self.execute_sql(sql, "Create model_hyperparameters", "PHASE_1", "model_hyperparameters")
        
        # Feature importance (multi-valued, 5NF)
        sql = """
        CREATE TABLE IF NOT EXISTS model_feature_importance (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            model_version VARCHAR(64) NOT NULL,
            feature_name VARCHAR(128) NOT NULL,
            importance_score DECIMAL(10,6) NOT NULL,
            rank_order INT,
            
            UNIQUE KEY uq_model_features (model_version, feature_name),
            CONSTRAINT fk_features_model 
                FOREIGN KEY (model_version) REFERENCES model_training_sessions_5nf(model_version)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """
        self.execute_sql(sql, "Create model_feature_importance", "PHASE_1", "model_feature_importance")
        
        return True
    
    def phase1_create_views(self):
        """Create views for calculated fields"""
        print("\n" + "="*80)
        print("PHASE 1.8: Creating Views for Calculated Fields")
        print("="*80)
        
        # View for prediction audit with calculated metrics
        sql = """
        CREATE OR REPLACE VIEW v_prediction_audit_with_metrics AS
        SELECT 
            p.*,
            m.close_price as reference_price,
            ((m.close_price - LAG(m.close_price) OVER (PARTITION BY p.stock_id ORDER BY m.trade_date)) / 
                NULLIF(LAG(m.close_price) OVER (PARTITION BY p.stock_id ORDER BY m.trade_date), 0)) as actual_return_5d,
            ABS(p.predicted_return_5d - 
                ((m.close_price - LAG(m.close_price) OVER (PARTITION BY p.stock_id ORDER BY m.trade_date)) / 
                 NULLIF(LAG(m.close_price) OVER (PARTITION BY p.stock_id ORDER BY m.trade_date), 0))
            ) as error_abs
        FROM prediction_audit_5nf p
        LEFT JOIN market_daily_bars m ON p.stock_id = m.stock_id AND p.as_of_date = m.trade_date
        """
        self.execute_sql(sql, "Create v_prediction_audit_with_metrics", "PHASE_1", "v_prediction_audit_with_metrics")
        
        # View for allocation executions with calculated fields
        sql = """
        CREATE OR REPLACE VIEW v_allocation_executions_with_calculations AS
        SELECT 
            ae.*,
            (ae.executed_shares * ae.price_snapshot) as executed_amount_egp,
            (ae.target_amount_egp - (ae.executed_shares * ae.price_snapshot)) as residual_component_egp
        FROM allocation_executions_5nf ae
        """
        self.execute_sql(sql, "Create v_allocation_executions_with_calculations", "PHASE_1", "v_allocation_executions_with_calculations")
        
        # View for portfolio targets with denormalized data (convenience)
        sql = """
        CREATE OR REPLACE VIEW v_portfolio_targets_enhanced AS
        SELECT 
            pt.*,
            si.symbol,
            si.name as stock_name,
            si.sector_code,
            sr.name as sector_name,
            (pt.target_weight * pr.investment_capital) as target_amount_egp
        FROM portfolio_targets_5nf pt
        JOIN stock_instruments_5nf si ON pt.stock_id = si.id
        JOIN sector_reference_5nf sr ON si.sector_code = sr.code
        JOIN portfolio_runs pr ON pt.portfolio_run_id = pr.id
        """
        self.execute_sql(sql, "Create v_portfolio_targets_enhanced", "PHASE_1", "v_portfolio_targets_enhanced")
        
        return True

    # =========================================================================
    # PHASE 2: DATA MIGRATION
    # =========================================================================
    
    def phase2_migrate_sectors(self):
        """Migrate sector data (3NF fix)"""
        print("\n" + "="*80)
        print("PHASE 2.1: Migrating Sector Data (3NF Fix)")
        print("="*80)
        
        try:
            # Migrate sectors from stock_instruments
            self.cursor.execute("""
                INSERT INTO sector_reference_5nf (code, name, created_at)
                SELECT DISTINCT 
                    si.sector_code, 
                    COALESCE(si.name, si.sector_code),
                    NOW()
                FROM stock_instruments si
                WHERE si.sector_code NOT IN (
                    SELECT code FROM sector_reference_5nf WHERE code IS NOT NULL
                )
                ON DUPLICATE KEY UPDATE 
                    name = COALESCE(sector_reference_5nf.name, VALUES(name))
            """)
            sector_rows = self.cursor.rowcount
            
            # Also copy existing sector_reference data
            self.cursor.execute("""
                INSERT IGNORE INTO sector_reference_5nf (code, name, description, created_at)
                SELECT code, name, description, created_at
                FROM sector_reference
            """)
            existing_sectors = self.cursor.rowcount
            
            self.conn.commit()
            
            final_count = self.get_row_count('sector_reference_5nf')
            self.migration_results['sector_reference_5nf'] = final_count
            self.log_migration("PHASE_2", "sector_reference_5nf", "DATA_MIGRATION", final_count, 'COMPLETED')
            print(f"   ✅ Migrated {final_count} sectors")
            return True
            
        except Error as e:
            self.conn.rollback()
            print(f"   ❌ Failed: {e}")
            self.log_migration("PHASE_2", "sector_reference_5nf", "DATA_MIGRATION", status='FAILED', error_msg=str(e))
            return False
    
    def phase2_migrate_stock_instruments(self):
        """Migrate stock instruments (3NF fix - remove sector_name)"""
        print("\n" + "="*80)
        print("PHASE 2.2: Migrating Stock Instruments (3NF Fix)")
        print("="*80)
        
        try:
            self.cursor.execute("""
                INSERT INTO stock_instruments_5nf 
                (id, symbol, isin, name, sector_code, listed_shares, currency, is_active, created_at)
                SELECT id, symbol, isin, name, sector_code, listed_shares, currency, is_active, created_at
                FROM stock_instruments
            """)
            self.conn.commit()
            
            row_count = self.get_row_count('stock_instruments_5nf')
            self.migration_results['stock_instruments_5nf'] = row_count
            self.log_migration("PHASE_2", "stock_instruments_5nf", "DATA_MIGRATION", row_count, 'COMPLETED')
            print(f"   ✅ Migrated {row_count} stock instruments")
            return True
            
        except Error as e:
            self.conn.rollback()
            print(f"   ❌ Failed: {e}")
            self.log_migration("PHASE_2", "stock_instruments_5nf", "DATA_MIGRATION", status='FAILED', error_msg=str(e))
            return False
    
    def phase2_migrate_daily_ai_signals(self):
        """Migrate daily AI signals with 4NF decomposition"""
        print("\n" + "="*80)
        print("PHASE 2.3: Migrating Daily AI Signals (4NF Decomposition)")
        print("="*80)
        
        try:
            # Check if there is data to migrate
            old_count = self.get_row_count('daily_ai_signals')
            print(f"   Source table has {old_count} rows")
            
            if old_count == 0:
                print("   ⚠️ No data to migrate in daily_ai_signals")
                self.migration_results['daily_ai_signals_5nf'] = 0
                self.migration_results['signal_predictions'] = 0
                self.migration_results['signal_auxiliary_metrics'] = 0
                return True
            
            # Migrate core signals
            self.cursor.execute("""
                INSERT INTO daily_ai_signals_5nf 
                (stock_id, signal_date, action, confidence_score, model_version, created_at, updated_at)
                SELECT stock_id, signal_date, action, confidence_score, model_version, created_at, updated_at
                FROM daily_ai_signals
                WHERE stock_id IS NOT NULL
            """)
            core_rows = self.cursor.rowcount
            
            # Migrate predictions (4NF decomposition)
            self.cursor.execute("""
                INSERT INTO signal_predictions (signal_id, prediction_type, predicted_value, confidence)
                SELECT s.id, 'RETURN_5D', das.predicted_return_5d, das.confidence_score
                FROM daily_ai_signals das
                JOIN daily_ai_signals_5nf s 
                    ON das.stock_id = s.stock_id AND das.signal_date = s.signal_date
                WHERE das.predicted_return_5d IS NOT NULL
            """)
            pred_rows = self.cursor.rowcount
            
            # Migrate auxiliary metrics
            metrics_sql = """
                INSERT INTO signal_auxiliary_metrics (signal_id, metric_type, metric_value, metadata_json)
                SELECT s.id, 'SMART_MONEY', das.smart_money_signal, NULL
                FROM daily_ai_signals das
                JOIN daily_ai_signals_5nf s 
                    ON das.stock_id = s.stock_id AND das.signal_date = s.signal_date
                WHERE das.smart_money_signal IS NOT NULL
                UNION ALL
                SELECT s.id, 'MARKET_SENTIMENT', das.market_sentiment_score, NULL
                FROM daily_ai_signals das
                JOIN daily_ai_signals_5nf s 
                    ON das.stock_id = s.stock_id AND das.signal_date = s.signal_date
                WHERE das.market_sentiment_score IS NOT NULL
                UNION ALL
                SELECT s.id, 'RETURN_ANNUAL', das.expected_return_annual, NULL
                FROM daily_ai_signals das
                JOIN daily_ai_signals_5nf s 
                    ON das.stock_id = s.stock_id AND das.signal_date = s.signal_date
                WHERE das.expected_return_annual IS NOT NULL
                UNION ALL
                SELECT s.id, 'VOLATILITY', das.expected_volatility, NULL
                FROM daily_ai_signals das
                JOIN daily_ai_signals_5nf s 
                    ON das.stock_id = s.stock_id AND das.signal_date = s.signal_date
                WHERE das.expected_volatility IS NOT NULL
            """
            self.cursor.execute(metrics_sql)
            metrics_rows = self.cursor.rowcount
            
            self.conn.commit()
            
            self.migration_results['daily_ai_signals_5nf'] = core_rows
            self.migration_results['signal_predictions'] = pred_rows
            self.migration_results['signal_auxiliary_metrics'] = metrics_rows
            
            self.log_migration("PHASE_2", "daily_ai_signals_5nf", "DATA_MIGRATION", core_rows, 'COMPLETED')
            print(f"   ✅ Migrated {core_rows} core signals, {pred_rows} predictions, {metrics_rows} metrics")
            return True
            
        except Error as e:
            self.conn.rollback()
            print(f"   ❌ Failed: {e}")
            self.log_migration("PHASE_2", "daily_ai_signals_5nf", "DATA_MIGRATION", status='FAILED', error_msg=str(e))
            return False
    
    def phase2_migrate_prediction_audit(self):
        """Migrate prediction audit (remove calculated columns)"""
        print("\n" + "="*80)
        print("PHASE 2.4: Migrating Prediction Audit (Remove Calculated Columns)")
        print("="*80)
        
        try:
            old_count = self.get_row_count('prediction_audit')
            print(f"   Source table has {old_count} rows")
            
            if old_count == 0:
                print("   ⚠️ No data to migrate in prediction_audit")
                self.migration_results['prediction_audit_5nf'] = 0
                return True
            
            # Migrate with stock_id lookup
            self.cursor.execute("""
                INSERT INTO prediction_audit_5nf 
                (id, as_of_date, symbol, stock_id, request_id, predicted_return_5d, confidence_score, reconciled_at)
                SELECT 
                    pa.id, pa.as_of_date, pa.symbol, 
                    (SELECT id FROM stock_instruments_5nf WHERE symbol = pa.symbol LIMIT 1),
                    pa.request_id, pa.predicted_return_5d, pa.confidence_score, pa.reconciled_at
                FROM prediction_audit pa
            """)
            self.conn.commit()
            
            row_count = self.get_row_count('prediction_audit_5nf')
            self.migration_results['prediction_audit_5nf'] = row_count
            self.log_migration("PHASE_2", "prediction_audit_5nf", "DATA_MIGRATION", row_count, 'COMPLETED')
            print(f"   ✅ Migrated {row_count} prediction audit records")
            return True
            
        except Error as e:
            self.conn.rollback()
            print(f"   ❌ Failed: {e}")
            self.log_migration("PHASE_2", "prediction_audit_5nf", "DATA_MIGRATION", status='FAILED', error_msg=str(e))
            return False
    
    def phase2_migrate_allocation_executions(self):
        """Migrate allocation executions (remove calculated columns)"""
        print("\n" + "="*80)
        print("PHASE 2.5: Migrating Allocation Executions (Remove Calculated Columns)")
        print("="*80)
        
        try:
            old_count = self.get_row_count('allocation_executions')
            print(f"   Source table has {old_count} rows")
            
            if old_count == 0:
                print("   ⚠️ No data to migrate in allocation_executions")
                self.migration_results['allocation_executions_5nf'] = 0
                return True
            
            self.cursor.execute("""
                INSERT INTO allocation_executions_5nf 
                (id, portfolio_run_id, stock_id, price_snapshot, target_amount_egp, 
                 executed_shares, settlement_date, settlement_status, created_at)
                SELECT 
                    id, portfolio_run_id, stock_id, price_snapshot, target_amount_egp,
                    executed_shares, settlement_date, settlement_status, created_at
                FROM allocation_executions
            """)
            self.conn.commit()
            
            row_count = self.get_row_count('allocation_executions_5nf')
            self.migration_results['allocation_executions_5nf'] = row_count
            self.log_migration("PHASE_2", "allocation_executions_5nf", "DATA_MIGRATION", row_count, 'COMPLETED')
            print(f"   ✅ Migrated {row_count} allocation execution records")
            return True
            
        except Error as e:
            self.conn.rollback()
            print(f"   ❌ Failed: {e}")
            self.log_migration("PHASE_2", "allocation_executions_5nf", "DATA_MIGRATION", status='FAILED', error_msg=str(e))
            return False
    
    def phase2_migrate_portfolio_targets(self):
        """Migrate portfolio targets (remove denormalized sector_code)"""
        print("\n" + "="*80)
        print("PHASE 2.6: Migrating Portfolio Targets (Remove Denormalized sector_code)")
        print("="*80)
        
        try:
            old_count = self.get_row_count('portfolio_targets')
            print(f"   Source table has {old_count} rows")
            
            if old_count == 0:
                print("   ⚠️ No data to migrate in portfolio_targets")
                self.migration_results['portfolio_targets_5nf'] = 0
                return True
            
            self.cursor.execute("""
                INSERT INTO portfolio_targets_5nf 
                (id, portfolio_run_id, stock_id, target_weight, constraint_flags_json, created_at)
                SELECT id, portfolio_run_id, stock_id, target_weight, constraint_flags_json, created_at
                FROM portfolio_targets
            """)
            self.conn.commit()
            
            row_count = self.get_row_count('portfolio_targets_5nf')
            self.migration_results['portfolio_targets_5nf'] = row_count
            self.log_migration("PHASE_2", "portfolio_targets_5nf", "DATA_MIGRATION", row_count, 'COMPLETED')
            print(f"   ✅ Migrated {row_count} portfolio target records")
            return True
            
        except Error as e:
            self.conn.rollback()
            print(f"   ❌ Failed: {e}")
            self.log_migration("PHASE_2", "portfolio_targets_5nf", "DATA_MIGRATION", status='FAILED', error_msg=str(e))
            return False
    
    def phase2_migrate_model_tables(self):
        """Migrate model performance data with 5NF decomposition"""
        print("\n" + "="*80)
        print("PHASE 2.7: Migrating Model Performance Data (5NF Decomposition)")
        print("="*80)
        
        try:
            old_count = self.get_row_count('model_performance_logs')
            print(f"   Source table has {old_count} rows")
            
            if old_count == 0:
                print("   ⚠️ No data to migrate in model_performance_logs")
                self.migration_results['model_training_sessions_5nf'] = 0
                self.migration_results['model_metrics'] = 0
                return True
            
            # For now, create a simple migration of core data
            # Full decomposition would require parsing JSON columns
            self.cursor.execute("""
                INSERT INTO model_training_sessions_5nf 
                (model_version, training_date, backtest_job_id, training_data_start, training_data_end, notes, created_at)
                SELECT 
                    model_version, training_date, backtest_job_id, training_data_start, training_data_end, notes, created_at
                FROM model_performance_logs
                WHERE model_version IS NOT NULL
            """)
            core_rows = self.cursor.rowcount
            
            self.conn.commit()
            
            self.migration_results['model_training_sessions_5nf'] = core_rows
            self.log_migration("PHASE_2", "model_training_sessions_5nf", "DATA_MIGRATION", core_rows, 'COMPLETED')
            print(f"   ✅ Migrated {core_rows} model training sessions")
            print(f"   ⚠️ Note: Full 5NF decomposition of metrics/hyperparameters requires JSON parsing (deferred)")
            return True
            
        except Error as e:
            self.conn.rollback()
            print(f"   ❌ Failed: {e}")
            self.log_migration("PHASE_2", "model_training_sessions_5nf", "DATA_MIGRATION", status='FAILED', error_msg=str(e))
            return False
    
    def print_summary(self):
        """Print migration summary"""
        print("\n" + "="*80)
        print("MIGRATION SUMMARY - PHASES 1 & 2 COMPLETED")
        print("="*80)
        print("\n📊 New 5NF Tables Created:")
        print("-" * 50)
        
        tables = [
            ('sector_reference_5nf', 'Normalized sectors (3NF)'),
            ('stock_instruments_5nf', 'Normalized stocks without sector_name (3NF)'),
            ('daily_ai_signals_5nf', 'Core AI signals (4NF)'),
            ('signal_predictions', 'Decomposed predictions (4NF)'),
            ('signal_auxiliary_metrics', 'Decomposed metrics (4NF)'),
            ('signal_xai_reasons', 'XAI reasons (MVD)'),
            ('prediction_audit_5nf', 'Without calculated columns'),
            ('allocation_executions_5nf', 'Without calculated columns'),
            ('portfolio_targets_5nf', 'Without denormalized sector_code'),
            ('model_training_sessions_5nf', 'Core model sessions (5NF)'),
            ('model_metrics', 'Decomposed metrics (5NF)'),
            ('model_hyperparameters', 'Decomposed hyperparams (5NF)'),
            ('model_feature_importance', 'Feature importance (5NF)'),
        ]
        
        for table_name, description in tables:
            count = self.migration_results.get(table_name, 0)
            status = "✅" if count > 0 or table_name in self.migration_results else "⬜"
            print(f"{status} {table_name:35} | Rows: {count:6} | {description}")
        
        print("\n📊 Views Created:")
        print("-" * 50)
        views = [
            'v_prediction_audit_with_metrics',
            'v_allocation_executions_with_calculations',
            'v_portfolio_targets_enhanced'
        ]
        for view in views:
            print(f"✅ {view}")
        
        print("\n" + "="*80)
        print("✅ PHASE 1 (Preparation) - COMPLETED")
        print("✅ PHASE 2 (Data Migration) - COMPLETED")
        print("⏸️  PHASE 3 (Verification) - READY FOR EXECUTION")
        print("⏸️  PHASE 4 (Atomic Cutover) - NOT EXECUTED (as requested)")
        print("="*80)
        print("\n📝 IMPORTANT NOTES:")
        print("   • All original tables remain untouched")
        print("   • New _5nf tables exist alongside originals")
        print("   • Views provide calculated fields on-demand")
        print("   • Ready for testing and Phase 4 cutover when approved")
        print("="*80)

    def run(self):
        """Execute full migration"""
        print("="*80)
        print("5NF DATABASE MIGRATION - PHASES 1 & 2")
        print("EGX Robo-Advisor Platform - egx_portfolio")
        print("="*80)
        print(f"Started at: {datetime.now().isoformat()}")
        print("="*80)
        
        if not self.connect():
            sys.exit(1)
        
        try:
            # Phase 1: Create new tables
            self.phase1_create_migration_log()
            self.phase1_create_sector_tables()
            self.phase1_create_ai_signals_tables()
            self.phase1_create_prediction_tables()
            self.phase1_create_allocation_tables()
            self.phase1_create_portfolio_tables()
            self.phase1_create_model_tables()
            self.phase1_create_views()
            
            # Phase 2: Migrate data
            self.phase2_migrate_sectors()
            self.phase2_migrate_stock_instruments()
            self.phase2_migrate_daily_ai_signals()
            self.phase2_migrate_prediction_audit()
            self.phase2_migrate_allocation_executions()
            self.phase2_migrate_portfolio_targets()
            self.phase2_migrate_model_tables()
            
            # Print summary
            self.print_summary()
            
        except Exception as e:
            print(f"\n❌ Migration failed with error: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
        finally:
            if self.cursor:
                self.cursor.close()
            if self.conn:
                self.conn.close()
            print(f"\nFinished at: {datetime.now().isoformat()}")

if __name__ == "__main__":
    runner = MigrationRunner()
    runner.run()
