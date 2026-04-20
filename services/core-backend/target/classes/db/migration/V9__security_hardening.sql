ALTER TABLE stock_instruments
    ADD COLUMN IF NOT EXISTS last_price DECIMAL(19, 4) NULL DEFAULT 0.0000 AFTER sector_code;

ALTER TABLE stock_instruments
    MODIFY COLUMN last_price DECIMAL(19, 4) NULL DEFAULT 0.0000;

UPDATE stock_instruments
SET last_price = 0.0000
WHERE last_price IS NULL;

ALTER TABLE users
    MODIFY COLUMN full_name VARCHAR(1024) NOT NULL,
    MODIFY COLUMN phone VARCHAR(255) NULL;

CREATE TABLE IF NOT EXISTS security_audit_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NULL,
    action VARCHAR(64) NOT NULL,
    outcome VARCHAR(16) NOT NULL,
    ip_address VARCHAR(64) NULL,
    user_agent VARCHAR(512) NULL,
    details_json JSON NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_security_audit_logs_user_id
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE INDEX ix_security_audit_logs_user_created
    ON security_audit_logs (user_id, created_at);

CREATE INDEX ix_security_audit_logs_action_created
    ON security_audit_logs (action, created_at);
