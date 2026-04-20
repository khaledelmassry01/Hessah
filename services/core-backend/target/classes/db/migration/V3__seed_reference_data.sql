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
