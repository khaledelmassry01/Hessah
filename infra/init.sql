-- EGX production database initialization script for MySQL 8.0
-- Consolidated from V1..V9 migrations.

SET NAMES utf8mb4;
SET time_zone = '+00:00';

-- -----------------------------------------------------------------------------
-- V1__baseline_schema.sql
-- -----------------------------------------------------------------------------

CREATE TABLE users (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    public_uuid CHAR(36) NOT NULL,
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(1024) NOT NULL,
    phone VARCHAR(255),
    kyc_status ENUM('PENDING', 'APPROVED', 'REJECTED') NOT NULL DEFAULT 'PENDING',
    account_status ENUM('ACTIVE', 'SUSPENDED', 'CLOSED') NOT NULL DEFAULT 'ACTIVE',
    role ENUM('USER', 'PRO', 'ADMIN') NOT NULL DEFAULT 'USER',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT uq_users_public_uuid UNIQUE (public_uuid),
    CONSTRAINT uq_users_email UNIQUE (email)
) ENGINE=InnoDB;

CREATE TABLE subscriptions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    tier ENUM('FREE', 'PREMIUM') NOT NULL DEFAULT 'FREE',
    status ENUM('ACTIVE', 'GRACE', 'CANCELED', 'EXPIRED') NOT NULL DEFAULT 'ACTIVE',
    started_at DATETIME(6),
    ends_at DATETIME(6),
    provider_ref VARCHAR(120),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_subscriptions_user_id FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB;
CREATE INDEX ix_subscriptions_user_tier_status ON subscriptions (user_id, tier, status);

CREATE TABLE wallets (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'EGP',
    available_balance DECIMAL(19, 4) NOT NULL DEFAULT 0.0000,
    locked_balance DECIMAL(19, 4) NOT NULL DEFAULT 0.0000,
    version BIGINT NOT NULL DEFAULT 0,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT uq_wallets_user_id UNIQUE (user_id),
    CONSTRAINT ck_wallets_available_nonnegative CHECK (available_balance >= 0),
    CONSTRAINT ck_wallets_locked_nonnegative CHECK (locked_balance >= 0),
    CONSTRAINT fk_wallets_user_id FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB;

CREATE TABLE wallet_ledger_entries (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    wallet_id BIGINT NOT NULL,
    entry_type ENUM('DEPOSIT', 'WITHDRAWAL', 'FEE_BUFFER', 'BUY_LOCK', 'SELL_SETTLE', 'DIVIDEND_CREDIT', 'RESIDUAL_RETURN') NOT NULL,
    amount DECIMAL(19, 4) NOT NULL,
    reference_type VARCHAR(64),
    reference_id BIGINT,
    settlement_status ENUM('PENDING', 'CLEARED', 'FAILED', 'N_A') NOT NULL DEFAULT 'N_A',
    notes VARCHAR(512),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_wallet_ledger_wallet_id FOREIGN KEY (wallet_id) REFERENCES wallets (id)
) ENGINE=InnoDB;
CREATE INDEX ix_wallet_ledger_wallet_created ON wallet_ledger_entries (wallet_id, created_at);

CREATE TABLE sector_reference (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT uq_sector_reference_code UNIQUE (code)
) ENGINE=InnoDB;

CREATE TABLE stock_instruments (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL,
    isin VARCHAR(32),
    name VARCHAR(255) NOT NULL,
    sector_code VARCHAR(64) NOT NULL,
    last_price DECIMAL(19, 4) NULL DEFAULT 0.0000,
    is_suspended BOOLEAN NOT NULL DEFAULT FALSE,
    suspension_reason VARCHAR(255),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT uq_stock_instruments_symbol UNIQUE (symbol),
    CONSTRAINT fk_stock_instruments_sector_code FOREIGN KEY (sector_code) REFERENCES sector_reference (code)
) ENGINE=InnoDB;
CREATE INDEX ix_stock_instruments_suspended_sector ON stock_instruments (is_suspended, sector_code);

CREATE TABLE market_daily_bars (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    stock_id BIGINT NOT NULL,
    trade_date DATE NOT NULL,
    close_price DECIMAL(19, 4) NOT NULL,
    volume BIGINT NOT NULL,
    is_halted BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT uq_market_daily_bars_stock_trade_date UNIQUE (stock_id, trade_date),
    CONSTRAINT fk_market_daily_bars_stock_id FOREIGN KEY (stock_id) REFERENCES stock_instruments (id)
) ENGINE=InnoDB;
CREATE INDEX ix_market_daily_bars_trade_date ON market_daily_bars (trade_date);

CREATE TABLE liquidity_snapshots (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    stock_id BIGINT NOT NULL,
    as_of_date DATE NOT NULL,
    adv30_shares BIGINT NOT NULL,
    adv30_value_egp DECIMAL(19, 4) NOT NULL,
    max_allocatable_value_egp DECIMAL(19, 4) NOT NULL,
    source VARCHAR(128),
    CONSTRAINT uq_liquidity_snapshots_stock_date UNIQUE (stock_id, as_of_date),
    CONSTRAINT fk_liquidity_snapshots_stock_id FOREIGN KEY (stock_id) REFERENCES stock_instruments (id)
) ENGINE=InnoDB;

CREATE TABLE risk_profiles (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    code ENUM('LOW', 'MEDIUM', 'HIGH') NOT NULL,
    description VARCHAR(255) NOT NULL,
    max_sector_weight DECIMAL(6, 4) NOT NULL,
    max_adv30_participation DECIMAL(6, 4) NOT NULL,
    premium_required BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT uq_risk_profiles_code UNIQUE (code)
) ENGINE=InnoDB;

CREATE TABLE portfolio_runs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_uuid CHAR(36) NOT NULL,
    user_id BIGINT NOT NULL,
    risk_level ENUM('LOW', 'MEDIUM', 'HIGH') NOT NULL,
    requested_amount_egp DECIMAL(19, 4) NOT NULL,
    fee_buffer_rate DECIMAL(6, 5) NOT NULL DEFAULT 0.00500,
    investable_budget_egp DECIMAL(19, 4) NOT NULL,
    run_status ENUM('PENDING', 'COMPLETED', 'FAILED', 'PARTIAL') NOT NULL DEFAULT 'PENDING',
    model_version VARCHAR(64),
    generated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT uq_portfolio_runs_request_uuid UNIQUE (request_uuid),
    CONSTRAINT fk_portfolio_runs_user_id FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB;
CREATE INDEX ix_portfolio_runs_user_generated ON portfolio_runs (user_id, generated_at);

CREATE TABLE portfolio_targets (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    portfolio_run_id BIGINT NOT NULL,
    stock_id BIGINT NOT NULL,
    target_weight DECIMAL(10, 8) NOT NULL,
    target_amount_egp DECIMAL(19, 4) NOT NULL,
    sector_code VARCHAR(64) NOT NULL,
    constraint_flags_json JSON,
    CONSTRAINT uq_portfolio_targets_run_stock UNIQUE (portfolio_run_id, stock_id),
    CONSTRAINT fk_portfolio_targets_run_id FOREIGN KEY (portfolio_run_id) REFERENCES portfolio_runs (id),
    CONSTRAINT fk_portfolio_targets_stock_id FOREIGN KEY (stock_id) REFERENCES stock_instruments (id),
    CONSTRAINT fk_portfolio_targets_sector_code FOREIGN KEY (sector_code) REFERENCES sector_reference (code)
) ENGINE=InnoDB;
CREATE INDEX ix_portfolio_targets_run_id ON portfolio_targets (portfolio_run_id);

CREATE TABLE allocation_executions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    portfolio_run_id BIGINT NOT NULL,
    stock_id BIGINT NOT NULL,
    price_snapshot DECIMAL(19, 4) NOT NULL,
    target_amount_egp DECIMAL(19, 4) NOT NULL,
    executed_shares BIGINT NOT NULL DEFAULT 0,
    executed_amount_egp DECIMAL(19, 4) NOT NULL DEFAULT 0.0000,
    residual_component_egp DECIMAL(19, 4) NOT NULL DEFAULT 0.0000,
    settlement_date DATE,
    settlement_status ENUM('PENDING', 'CLEARED', 'FAILED') NOT NULL DEFAULT 'PENDING',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_allocation_executions_run_id FOREIGN KEY (portfolio_run_id) REFERENCES portfolio_runs (id),
    CONSTRAINT fk_allocation_executions_stock_id FOREIGN KEY (stock_id) REFERENCES stock_instruments (id)
) ENGINE=InnoDB;
CREATE INDEX ix_allocation_executions_run_status ON allocation_executions (portfolio_run_id, settlement_status);

CREATE TABLE trade_orders (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    portfolio_run_id BIGINT,
    stock_id BIGINT NOT NULL,
    side ENUM('BUY', 'SELL') NOT NULL,
    order_qty BIGINT NOT NULL,
    filled_qty BIGINT NOT NULL DEFAULT 0,
    avg_fill_price DECIMAL(19, 4),
    order_status ENUM('NEW', 'PARTIALLY_FILLED', 'FILLED', 'REJECTED', 'CANCELED') NOT NULL DEFAULT 'NEW',
    trade_date DATE NOT NULL,
    settlement_date DATE,
    settlement_status ENUM('PENDING', 'CLEARED', 'FAILED') NOT NULL DEFAULT 'PENDING',
    rejection_reason VARCHAR(255),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_trade_orders_user_id FOREIGN KEY (user_id) REFERENCES users (id),
    CONSTRAINT fk_trade_orders_portfolio_run_id FOREIGN KEY (portfolio_run_id) REFERENCES portfolio_runs (id),
    CONSTRAINT fk_trade_orders_stock_id FOREIGN KEY (stock_id) REFERENCES stock_instruments (id),
    CONSTRAINT ck_trade_orders_order_qty_positive CHECK (order_qty > 0)
) ENGINE=InnoDB;
CREATE INDEX ix_trade_orders_user_stock_settlement ON trade_orders (user_id, stock_id, settlement_status);
CREATE INDEX ix_trade_orders_trade_date ON trade_orders (trade_date);

CREATE TABLE position_lots (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    stock_id BIGINT NOT NULL,
    source_order_id BIGINT NOT NULL,
    quantity_total BIGINT NOT NULL,
    quantity_available BIGINT NOT NULL,
    avg_cost DECIMAL(19, 4) NOT NULL,
    acquisition_date DATE NOT NULL,
    settlement_date DATE NOT NULL,
    settlement_status ENUM('PENDING', 'CLEARED', 'FAILED') NOT NULL DEFAULT 'PENDING',
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_position_lots_user_id FOREIGN KEY (user_id) REFERENCES users (id),
    CONSTRAINT fk_position_lots_stock_id FOREIGN KEY (stock_id) REFERENCES stock_instruments (id),
    CONSTRAINT fk_position_lots_order_id FOREIGN KEY (source_order_id) REFERENCES trade_orders (id),
    CONSTRAINT ck_position_lots_qty_nonnegative CHECK (quantity_available >= 0),
    CONSTRAINT ck_position_lots_qty_bounds CHECK (quantity_available <= quantity_total)
) ENGINE=InnoDB;
CREATE INDEX ix_position_lots_user_stock_status ON position_lots (user_id, stock_id, settlement_status);

CREATE TABLE corporate_actions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    stock_id BIGINT NOT NULL,
    action_type ENUM('STOCK_SPLIT', 'CASH_DIVIDEND') NOT NULL,
    ex_date DATE NOT NULL,
    record_date DATE,
    payable_date DATE,
    split_from INT,
    split_to INT,
    cash_dividend_per_share DECIMAL(19, 6),
    ingestion_status ENUM('NEW', 'PROCESSED', 'FAILED') NOT NULL DEFAULT 'NEW',
    processed_at DATETIME(6),
    CONSTRAINT uq_corporate_actions_stock_type_exdate UNIQUE (stock_id, action_type, ex_date),
    CONSTRAINT fk_corporate_actions_stock_id FOREIGN KEY (stock_id) REFERENCES stock_instruments (id)
) ENGINE=InnoDB;

CREATE TABLE corporate_action_journal (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    corporate_action_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    position_lot_id BIGINT,
    quantity_before BIGINT,
    quantity_after BIGINT,
    avg_cost_before DECIMAL(19, 4),
    avg_cost_after DECIMAL(19, 4),
    cash_credited_egp DECIMAL(19, 4),
    wallet_ledger_entry_id BIGINT,
    processed_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_corp_journal_action_id FOREIGN KEY (corporate_action_id) REFERENCES corporate_actions (id),
    CONSTRAINT fk_corp_journal_user_id FOREIGN KEY (user_id) REFERENCES users (id),
    CONSTRAINT fk_corp_journal_lot_id FOREIGN KEY (position_lot_id) REFERENCES position_lots (id),
    CONSTRAINT fk_corp_journal_ledger_id FOREIGN KEY (wallet_ledger_entry_id) REFERENCES wallet_ledger_entries (id)
) ENGINE=InnoDB;

CREATE TABLE rebalance_policies (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    drift_threshold_pct DECIMAL(6, 3) NOT NULL DEFAULT 5.000,
    auto_rebalance_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT uq_rebalance_policies_user_id UNIQUE (user_id),
    CONSTRAINT fk_rebalance_policies_user_id FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB;

CREATE TABLE rebalance_alerts (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    portfolio_run_id BIGINT NOT NULL,
    as_of_date DATE NOT NULL,
    total_drift_pct DECIMAL(6, 3) NOT NULL,
    recommendation_json JSON NOT NULL,
    alert_status ENUM('OPEN', 'ACKNOWLEDGED', 'DISMISSED', 'EXECUTED') NOT NULL DEFAULT 'OPEN',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_rebalance_alerts_user_id FOREIGN KEY (user_id) REFERENCES users (id),
    CONSTRAINT fk_rebalance_alerts_run_id FOREIGN KEY (portfolio_run_id) REFERENCES portfolio_runs (id)
) ENGINE=InnoDB;
CREATE INDEX ix_rebalance_alerts_user_status_date ON rebalance_alerts (user_id, alert_status, as_of_date);

CREATE TABLE stop_rules (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    stock_id BIGINT NOT NULL,
    portfolio_run_id BIGINT,
    stop_loss_pct DECIMAL(6, 3) NOT NULL,
    take_profit_pct DECIMAL(6, 3) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_stop_rules_user_id FOREIGN KEY (user_id) REFERENCES users (id),
    CONSTRAINT fk_stop_rules_stock_id FOREIGN KEY (stock_id) REFERENCES stock_instruments (id),
    CONSTRAINT fk_stop_rules_run_id FOREIGN KEY (portfolio_run_id) REFERENCES portfolio_runs (id)
) ENGINE=InnoDB;

CREATE TABLE stop_alerts (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    stop_rule_id BIGINT NOT NULL,
    trigger_type ENUM('STOP_LOSS', 'TAKE_PROFIT') NOT NULL,
    trigger_price DECIMAL(19, 4) NOT NULL,
    market_price DECIMAL(19, 4) NOT NULL,
    triggered_at DATETIME(6) NOT NULL,
    alert_status ENUM('OPEN', 'RESOLVED', 'DISMISSED') NOT NULL DEFAULT 'OPEN',
    CONSTRAINT fk_stop_alerts_rule_id FOREIGN KEY (stop_rule_id) REFERENCES stop_rules (id)
) ENGINE=InnoDB;

CREATE TABLE backtest_jobs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    request_payload_json JSON NOT NULL,
    result_summary_json JSON,
    status ENUM('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED') NOT NULL DEFAULT 'QUEUED',
    started_at DATETIME(6),
    finished_at DATETIME(6),
    CONSTRAINT fk_backtest_jobs_user_id FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB;
CREATE INDEX ix_backtest_jobs_user_status_started ON backtest_jobs (user_id, status, started_at);

CREATE TABLE ai_prediction_audit (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    portfolio_run_id BIGINT NOT NULL,
    request_json JSON NOT NULL,
    response_json JSON,
    latency_ms INT,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_ai_prediction_audit_run_id FOREIGN KEY (portfolio_run_id) REFERENCES portfolio_runs (id)
) ENGINE=InnoDB;
CREATE INDEX ix_ai_prediction_audit_run_created ON ai_prediction_audit (portfolio_run_id, created_at);

-- -----------------------------------------------------------------------------
-- V2__database_triggers.sql
-- -----------------------------------------------------------------------------

DELIMITER $$

CREATE TRIGGER trg_wallet_nonnegative_before_update
BEFORE UPDATE ON wallets
FOR EACH ROW
BEGIN
    IF NEW.available_balance < 0 OR NEW.locked_balance < 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Wallet balances cannot be negative';
    END IF;
END$$

CREATE TRIGGER trg_trade_order_settlement_t2_before_insert
BEFORE INSERT ON trade_orders
FOR EACH ROW
BEGIN
    IF NEW.trade_date IS NULL THEN
        SET NEW.trade_date = CURRENT_DATE();
    END IF;

    IF NEW.settlement_date IS NULL THEN
        SET NEW.settlement_date = DATE_ADD(NEW.trade_date, INTERVAL 2 DAY);
    END IF;

    IF NEW.settlement_status IS NULL THEN
        SET NEW.settlement_status = 'PENDING';
    END IF;
END$$

CREATE TRIGGER trg_sell_block_uncleared_before_insert
BEFORE INSERT ON trade_orders
FOR EACH ROW
BEGIN
    DECLARE cleared_qty BIGINT DEFAULT 0;

    IF NEW.side = 'SELL' THEN
        SELECT COALESCE(SUM(quantity_available), 0)
          INTO cleared_qty
          FROM position_lots
         WHERE user_id = NEW.user_id
           AND stock_id = NEW.stock_id
           AND settlement_status = 'CLEARED';

        IF cleared_qty < NEW.order_qty THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'Insufficient cleared quantity for SELL order (T+2 rule)';
        END IF;
    END IF;
END$$

CREATE TRIGGER trg_default_subscription_tier_before_insert
BEFORE INSERT ON subscriptions
FOR EACH ROW
BEGIN
    IF NEW.tier IS NULL THEN
        SET NEW.tier = 'FREE';
    END IF;

    IF NEW.status IS NULL THEN
        SET NEW.status = 'ACTIVE';
    END IF;

    IF NEW.started_at IS NULL THEN
        SET NEW.started_at = CURRENT_TIMESTAMP(6);
    END IF;
END$$

CREATE TRIGGER trg_allocation_shares_integrity_before_insert
BEFORE INSERT ON allocation_executions
FOR EACH ROW
BEGIN
    IF NEW.executed_shares IS NULL THEN
        SET NEW.executed_shares = 0;
    END IF;

    IF NEW.executed_shares < 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'executed_shares cannot be negative';
    END IF;
END$$

CREATE TRIGGER trg_allocation_shares_integrity_before_update
BEFORE UPDATE ON allocation_executions
FOR EACH ROW
BEGIN
    IF NEW.executed_shares < 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'executed_shares cannot be negative';
    END IF;
END$$

DELIMITER ;

-- -----------------------------------------------------------------------------
-- V3__seed_reference_data.sql
-- -----------------------------------------------------------------------------

INSERT INTO sector_reference (code, name) VALUES
    ('BANKS', 'Banks'),
    ('FIN_SERV', 'Financial Services'),
    ('INDUSTRIALS', 'Industrials'),
    ('REAL_ESTATE', 'Real Estate'),
    ('TELECOM', 'Telecommunication'),
    ('ENERGY', 'Energy'),
    ('CONSUMER', 'Consumer Staples & Discretionary'),
    ('HEALTHCARE', 'Healthcare'),
    ('MATERIALS', 'Materials'),
    ('TRANSPORT', 'Transport & Logistics'),
    ('UTILITIES', 'Utilities')
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    is_active = TRUE;

INSERT INTO risk_profiles (
    code,
    description,
    max_sector_weight,
    max_adv30_participation,
    premium_required
) VALUES
    ('LOW', 'Long-term conservative profile for freemium users', 0.4000, 0.0500, FALSE),
    ('MEDIUM', 'Balanced growth profile for premium users', 0.4000, 0.0500, TRUE),
    ('HIGH', 'Aggressive profile for premium users', 0.4000, 0.0500, TRUE)
ON DUPLICATE KEY UPDATE
    description = VALUES(description),
    max_sector_weight = VALUES(max_sector_weight),
    max_adv30_participation = VALUES(max_adv30_participation),
    premium_required = VALUES(premium_required);

-- -----------------------------------------------------------------------------
-- V4__extend_stop_alert_status.sql
-- -----------------------------------------------------------------------------

ALTER TABLE stop_alerts
    MODIFY COLUMN alert_status ENUM('TRIGGERED', 'OPEN', 'RESOLVED', 'DISMISSED') NOT NULL DEFAULT 'OPEN';

-- -----------------------------------------------------------------------------
-- V5__add_token_blacklist.sql
-- -----------------------------------------------------------------------------

CREATE TABLE token_blacklist (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    token VARCHAR(2048) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT uq_token_blacklist_token UNIQUE (token)
) ENGINE=InnoDB;

CREATE INDEX ix_token_blacklist_expires_at ON token_blacklist (expires_at);

-- -----------------------------------------------------------------------------
-- V6__add_user_sessions.sql
-- -----------------------------------------------------------------------------

CREATE TABLE user_sessions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    refresh_token_jti VARCHAR(64) NOT NULL,
    user_agent VARCHAR(512) NULL,
    ip_address VARCHAR(64) NULL,
    last_active DATETIME(6) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    is_revoked TINYINT(1) NOT NULL DEFAULT 0,
    CONSTRAINT fk_user_sessions_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT uq_user_sessions_refresh_token_jti UNIQUE (refresh_token_jti)
) ENGINE=InnoDB;

CREATE INDEX ix_user_sessions_user_active ON user_sessions (user_id, is_revoked, expires_at);
CREATE INDEX ix_user_sessions_last_active ON user_sessions (last_active);

-- -----------------------------------------------------------------------------
-- V7__historical_market_data_and_model_performance.sql
-- -----------------------------------------------------------------------------

ALTER TABLE market_daily_bars
    ADD COLUMN open_price DECIMAL(19, 4) NULL AFTER trade_date,
    ADD COLUMN high_price DECIMAL(19, 4) NULL AFTER open_price,
    ADD COLUMN low_price DECIMAL(19, 4) NULL AFTER high_price;

UPDATE market_daily_bars
SET open_price = close_price,
    high_price = close_price,
    low_price = close_price
WHERE open_price IS NULL
   OR high_price IS NULL
   OR low_price IS NULL;

ALTER TABLE market_daily_bars
    MODIFY COLUMN open_price DECIMAL(19, 4) NOT NULL,
    MODIFY COLUMN high_price DECIMAL(19, 4) NOT NULL,
    MODIFY COLUMN low_price DECIMAL(19, 4) NOT NULL;

CREATE TABLE model_performance_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id VARCHAR(64),
    user_id BIGINT,
    risk_level VARCHAR(16) NOT NULL,
    model_version VARCHAR(64) NOT NULL,
    historical_date DATE NOT NULL,
    evaluation_date DATE NOT NULL,
    horizon_days INT NOT NULL,
    budget_egp DECIMAL(19, 4) NOT NULL,
    predicted_return DECIMAL(12, 8) NOT NULL,
    actual_return DECIMAL(12, 8) NOT NULL,
    prediction_error DECIMAL(12, 8) NOT NULL,
    risk_free_rate DECIMAL(8, 6) NOT NULL,
    covariance_shrinkage DECIMAL(8, 6) NOT NULL,
    run_status VARCHAR(16) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_model_performance_user_id FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB;

CREATE INDEX ix_model_performance_risk_created
    ON model_performance_logs (risk_level, created_at);

CREATE INDEX ix_model_performance_params
    ON model_performance_logs (risk_level, risk_free_rate, covariance_shrinkage);

-- -----------------------------------------------------------------------------
-- V8__add_stock_last_price.sql
-- -----------------------------------------------------------------------------

SET @has_last_price := (
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'stock_instruments'
      AND column_name = 'last_price'
);

SET @add_last_price_sql := IF(
    @has_last_price = 0,
    'ALTER TABLE stock_instruments ADD COLUMN last_price DECIMAL(19, 4) NULL DEFAULT 0.0000 AFTER sector_code',
    'SELECT 1'
);

PREPARE add_last_price_stmt FROM @add_last_price_sql;
EXECUTE add_last_price_stmt;
DEALLOCATE PREPARE add_last_price_stmt;

ALTER TABLE stock_instruments
    MODIFY COLUMN last_price DECIMAL(19, 4) NULL DEFAULT 0.0000;

UPDATE stock_instruments si
JOIN (
    SELECT m.stock_id, m.close_price
    FROM market_daily_bars m
    JOIN (
        SELECT stock_id, MAX(trade_date) AS latest_trade_date
        FROM market_daily_bars
        GROUP BY stock_id
    ) latest ON latest.stock_id = m.stock_id AND latest.latest_trade_date = m.trade_date
) lp ON lp.stock_id = si.id
SET si.last_price = lp.close_price;

UPDATE stock_instruments
SET last_price = 0.0000
WHERE last_price IS NULL;

-- -----------------------------------------------------------------------------
-- V9__security_hardening.sql
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS security_audit_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NULL,
    action VARCHAR(64) NOT NULL,
    outcome VARCHAR(16) NOT NULL,
    ip_address VARCHAR(64) NULL,
    user_agent VARCHAR(512) NULL,
    details_json JSON NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_security_audit_logs_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE INDEX ix_security_audit_logs_user_created
    ON security_audit_logs (user_id, created_at);

CREATE INDEX ix_security_audit_logs_action_created
    ON security_audit_logs (action, created_at);

-- -----------------------------------------------------------------------------
-- Static test bootstrap for local integration
-- -----------------------------------------------------------------------------

INSERT INTO users (
    id,
    public_uuid,
    email,
    password_hash,
    full_name,
    phone,
    kyc_status,
    account_status,
    role,
    created_at,
    updated_at
) VALUES
(
    1,
    '00000000-0000-0000-0000-000000000001',
    'integration-user@egx.local',
    '$2a$10$7Q2vM9jC6p6zWxM8h1T7R.u0V7bR1qFv3m2l8d9kP4s6Y1w3u5h7e',
    'Integration Test User',
    NULL,
    'APPROVED',
    'ACTIVE',
    'USER',
    CURRENT_TIMESTAMP(6),
    CURRENT_TIMESTAMP(6)
),
(
    2,
    '00000000-0000-0000-0000-000000000002',
    'integration-user-2@egx.local',
    '$2a$10$7Q2vM9jC6p6zWxM8h1T7R.u0V7bR1qFv3m2l8d9kP4s6Y1w3u5h7e',
    'Integration Test User 2',
    NULL,
    'APPROVED',
    'ACTIVE',
    'USER',
    CURRENT_TIMESTAMP(6),
    CURRENT_TIMESTAMP(6)
),
(
    3,
    '00000000-0000-0000-0000-000000000003',
    'admin@optimizer.com',
    '$2a$10$7Q2vM9jC6p6zWxM8h1T7R.u0V7bR1qFv3m2l8d9kP4s6Y1w3u5h7e',
    'System Admin',
    NULL,
    'APPROVED',
    'ACTIVE',
    'ADMIN',
    CURRENT_TIMESTAMP(6),
    CURRENT_TIMESTAMP(6)
)
ON DUPLICATE KEY UPDATE
    full_name = VALUES(full_name),
    kyc_status = 'APPROVED',
    account_status = 'ACTIVE',
    role = VALUES(role),
    updated_at = CURRENT_TIMESTAMP(6);

INSERT INTO wallets (
    user_id,
    currency,
    available_balance,
    locked_balance,
    version,
    created_at,
    updated_at
) VALUES
(
    1,
    'EGP',
    1000000.0000,
    0.0000,
    0,
    CURRENT_TIMESTAMP(6),
    CURRENT_TIMESTAMP(6)
),
(
    2,
    'EGP',
    1000000.0000,
    0.0000,
    0,
    CURRENT_TIMESTAMP(6),
    CURRENT_TIMESTAMP(6)
),
(
    3,
    'EGP',
    1000000.0000,
    0.0000,
    0,
    CURRENT_TIMESTAMP(6),
    CURRENT_TIMESTAMP(6)
)
ON DUPLICATE KEY UPDATE
    currency = 'EGP',
    available_balance = 1000000.0000,
    updated_at = CURRENT_TIMESTAMP(6);

DELETE FROM subscriptions WHERE user_id IN (1, 2, 3);

INSERT INTO subscriptions (
    user_id,
    tier,
    status,
    started_at,
    ends_at,
    provider_ref,
    created_at,
    updated_at
) VALUES
(
    1,
    'PREMIUM',
    'ACTIVE',
    CURRENT_TIMESTAMP(6),
    NULL,
    'STATIC_SEED_PREMIUM_1',
    CURRENT_TIMESTAMP(6),
    CURRENT_TIMESTAMP(6)
),
(
    2,
    'PREMIUM',
    'ACTIVE',
    CURRENT_TIMESTAMP(6),
    NULL,
    'STATIC_SEED_PREMIUM_2',
    CURRENT_TIMESTAMP(6),
    CURRENT_TIMESTAMP(6)
),
(
    3,
    'PREMIUM',
    'ACTIVE',
    CURRENT_TIMESTAMP(6),
    NULL,
    'STATIC_SEED_PREMIUM_3',
    CURRENT_TIMESTAMP(6),
    CURRENT_TIMESTAMP(6)
);

-- -----------------------------------------------------------------------------
-- RBAC Tables for Role-Based Access Control
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS roles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(64) NOT NULL,
    description VARCHAR(255),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT uq_roles_name UNIQUE (name)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS permissions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(64) NOT NULL,
    description VARCHAR(255),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT uq_permissions_name UNIQUE (name)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS user_roles (
    user_id BIGINT NOT NULL,
    role_id INT NOT NULL,
    PRIMARY KEY (user_id, role_id),
    CONSTRAINT fk_user_roles_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_user_roles_role_id FOREIGN KEY (role_id) REFERENCES roles (id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id INT NOT NULL,
    permission_id INT NOT NULL,
    PRIMARY KEY (role_id, permission_id),
    CONSTRAINT fk_role_permissions_role_id FOREIGN KEY (role_id) REFERENCES roles (id) ON DELETE CASCADE,
    CONSTRAINT fk_role_permissions_permission_id FOREIGN KEY (permission_id) REFERENCES permissions (id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Seed default roles
INSERT IGNORE INTO roles (id, name, description, created_at, updated_at) VALUES
(1, 'USER', 'Standard user with basic access', CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6)),
(2, 'PRO', 'Premium user with advanced features', CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6)),
(3, 'ADMIN', 'Administrator with full access', CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6));
