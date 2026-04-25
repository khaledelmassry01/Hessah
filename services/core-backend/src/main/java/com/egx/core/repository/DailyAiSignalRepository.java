package com.egx.core.repository;

import com.egx.core.domain.DailyAiSignal;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

@Repository
public interface DailyAiSignalRepository extends JpaRepository<DailyAiSignal, Long> {

    /**
     * Find the latest signal for a specific symbol on a given date.
     */
    Optional<DailyAiSignal> findBySymbolAndSignalDate(String symbol, LocalDate signalDate);

    /**
     * Find all signals for a specific date.
     */
    List<DailyAiSignal> findBySignalDate(LocalDate signalDate);

    /**
     * Find the latest signal for a symbol (most recent date).
     */
    @Query("SELECT s FROM DailyAiSignal s WHERE s.symbol = :symbol ORDER BY s.signalDate DESC LIMIT 1")
    Optional<DailyAiSignal> findLatestBySymbol(@Param("symbol") String symbol);

    /**
     * Find latest signals for multiple symbols.
     */
    @Query("""
        SELECT s FROM DailyAiSignal s
        WHERE s.symbol IN :symbols
        AND s.signalDate = (
            SELECT MAX(s2.signalDate) FROM DailyAiSignal s2 WHERE s2.symbol = s.symbol
        )
        """)
    List<DailyAiSignal> findLatestForSymbols(@Param("symbols") List<String> symbols);

    /**
     * Find all signals for the most recent date.
     */
    @Query("SELECT s FROM DailyAiSignal s WHERE s.signalDate = (SELECT MAX(s2.signalDate) FROM DailyAiSignal s2)")
    List<DailyAiSignal> findAllLatestSignals();

    /**
     * Delete old signals (for cleanup).
     */
    void deleteBySignalDateBefore(LocalDate cutoffDate);
}
