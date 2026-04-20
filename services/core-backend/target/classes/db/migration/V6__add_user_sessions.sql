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
