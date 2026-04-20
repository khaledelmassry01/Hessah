package com.egx.core.repository;

import com.egx.core.domain.PositionLot;
import com.egx.core.domain.enums.SettlementStatus;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface PositionLotRepository extends JpaRepository<PositionLot, Long> {
    List<PositionLot> findByUserIdAndStockId(Long userId, Long stockId);
    List<PositionLot> findByUserIdAndStockIdAndSettlementStatus(Long userId, Long stockId, SettlementStatus settlementStatus);
}
