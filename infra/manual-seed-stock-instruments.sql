-- Manual EGX30 seed script for stock_instruments.
-- Run this against egx_portfolio when instrument sync is unavailable.

START TRANSACTION;

INSERT INTO sector_reference (code, name)
VALUES
    ('BANKS', 'Banks'),
    ('FIN_SERV', 'Financial Services'),
    ('INDUSTRIALS', 'Industrials'),
    ('REAL_ESTATE', 'Real Estate'),
    ('TELECOM', 'Telecommunications'),
    ('ENERGY', 'Energy'),
    ('CONSUMER', 'Consumer Staples & Discretionary'),
    ('HEALTHCARE', 'Healthcare'),
    ('MATERIALS', 'Materials'),
    ('TECHNOLOGY', 'Technology')
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    is_active = TRUE;

INSERT INTO stock_instruments (
    symbol,
    name,
    sector_code,
    last_price,
    is_suspended,
    suspension_reason
)
VALUES
    ('COMI.CA', 'Commercial International Bank', 'BANKS', 1.0000, FALSE, NULL),
    ('HRHO.CA', 'EFG Holding', 'FIN_SERV', 1.0000, FALSE, NULL),
    ('SWDY.CA', 'Elsewedy Electric', 'INDUSTRIALS', 1.0000, FALSE, NULL),
    ('ETEL.CA', 'Telecom Egypt', 'TELECOM', 1.0000, FALSE, NULL),
    ('EFIH.CA', 'eFinance Investment Group', 'TECHNOLOGY', 1.0000, FALSE, NULL),
    ('ABUK.CA', 'Abu Qir Fertilizers', 'MATERIALS', 1.0000, FALSE, NULL),
    ('FWRY.CA', 'Fawry', 'TECHNOLOGY', 1.0000, FALSE, NULL),
    ('PHDC.CA', 'Palm Hills Development', 'REAL_ESTATE', 1.0000, FALSE, NULL),
    ('TMGH.CA', 'Talaat Moustafa Group', 'REAL_ESTATE', 1.0000, FALSE, NULL),
    ('ORWE.CA', 'Oriental Weavers', 'CONSUMER', 1.0000, FALSE, NULL),
    ('EAST.CA', 'Eastern Company', 'CONSUMER', 1.0000, FALSE, NULL),
    ('AMOC.CA', 'Alexandria Mineral Oils', 'ENERGY', 1.0000, FALSE, NULL),
    ('MFPC.CA', 'Misr Fertilizers Production', 'MATERIALS', 1.0000, FALSE, NULL),
    ('SKPC.CA', 'Sidi Kerir Petrochemicals', 'MATERIALS', 1.0000, FALSE, NULL),
    ('CCAP.CA', 'Citadel Capital', 'FIN_SERV', 1.0000, FALSE, NULL),
    ('HELI.CA', 'Heliopolis Housing', 'REAL_ESTATE', 1.0000, FALSE, NULL),
    ('PACH.CA', 'Paint and Chemicals Industries', 'MATERIALS', 1.0000, FALSE, NULL),
    ('EKHO.CA', 'Egypt Kuwait Holding', 'INDUSTRIALS', 1.0000, FALSE, NULL),
    ('MICH.CA', 'Misr Chemical Industries', 'MATERIALS', 1.0000, FALSE, NULL),
    ('ALCN.CA', 'Alexandria Containers', 'INDUSTRIALS', 1.0000, FALSE, NULL),
    ('ESRS.CA', 'Ezz Steel', 'MATERIALS', 1.0000, FALSE, NULL),
    ('JUFO.CA', 'Juhayna Food Industries', 'CONSUMER', 1.0000, FALSE, NULL),
    ('DOMT.CA', 'Domty', 'CONSUMER', 1.0000, FALSE, NULL),
    ('GDWA.CA', 'Gadwa for Industrial Development', 'FIN_SERV', 1.0000, FALSE, NULL),
    ('CIEB.CA', 'Credit Agricole Egypt', 'BANKS', 1.0000, FALSE, NULL),
    ('AUTO.CA', 'GB Corp', 'CONSUMER', 1.0000, FALSE, NULL),
    ('BTFH.CA', 'Beltone Holding', 'FIN_SERV', 1.0000, FALSE, NULL),
    ('OBRI.CA', 'Obour Land', 'CONSUMER', 1.0000, FALSE, NULL),
    ('RAYA.CA', 'Raya Holding', 'TECHNOLOGY', 1.0000, FALSE, NULL),
    ('CLHO.CA', 'Cleopatra Hospitals', 'HEALTHCARE', 1.0000, FALSE, NULL)
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    sector_code = VALUES(sector_code),
    is_suspended = FALSE,
    suspension_reason = NULL,
    updated_at = CURRENT_TIMESTAMP(6),
    last_price = CASE
        WHEN stock_instruments.last_price IS NULL OR stock_instruments.last_price <= 0
            THEN VALUES(last_price)
        ELSE stock_instruments.last_price
    END;

COMMIT;
