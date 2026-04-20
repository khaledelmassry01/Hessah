CREATE TABLE token_blacklist (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    token VARCHAR(2048) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT uq_token_blacklist_token UNIQUE (token)
) ENGINE=InnoDB;

CREATE INDEX ix_token_blacklist_expires_at ON token_blacklist (expires_at);
