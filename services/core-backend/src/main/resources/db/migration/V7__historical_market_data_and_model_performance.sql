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
