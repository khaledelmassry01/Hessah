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
