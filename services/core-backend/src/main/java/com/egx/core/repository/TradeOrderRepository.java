package com.egx.core.repository;

import com.egx.core.domain.TradeOrder;
import com.egx.core.domain.enums.SettlementStatus;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface TradeOrderRepository extends JpaRepository<TradeOrder, Long> {
    List<TradeOrder> findByUserIdAndSettlementStatus(Long userId, SettlementStatus settlementStatus);

    List<TradeOrder> findByUserIdAndPortfolioRunId(Long userId, Long portfolioRunId);
}
