ALTER TABLE stock_instruments
    ADD COLUMN IF NOT EXISTS last_price DECIMAL(19, 4) NULL DEFAULT 0.0000 AFTER sector_code;

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
