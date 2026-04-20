package com.egx.core.repository;

import com.egx.core.domain.MarketDailyBar;
import org.springframework.data.jpa.repository.JpaRepository;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

public interface MarketDailyBarRepository extends JpaRepository<MarketDailyBar, Long> {
    Optional<MarketDailyBar> findTopByStockIdOrderByTradeDateDesc(Long stockId);
    Optional<MarketDailyBar> findByStockIdAndTradeDate(Long stockId, LocalDate tradeDate);
    List<MarketDailyBar> findByStockIdAndTradeDateBetween(Long stockId, LocalDate startDate, LocalDate endDate);
}
