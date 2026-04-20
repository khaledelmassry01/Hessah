package com.egx.core.repository;

import com.egx.core.domain.StockInstrument;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface StockInstrumentRepository extends JpaRepository<StockInstrument, Long> {
    Optional<StockInstrument> findBySymbol(String symbol);
    List<StockInstrument> findBySymbolIn(List<String> symbols);
    List<StockInstrument> findByIsSuspendedFalse();
}
