package com.egx.core.service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.egx.core.domain.AllocationExecution;
import com.egx.core.domain.MarketDailyBar;
import com.egx.core.domain.PortfolioTarget;
import com.egx.core.domain.StockInstrument;
import com.egx.core.domain.enums.SettlementStatus;
import com.egx.core.repository.AllocationExecutionRepository;
import com.egx.core.repository.MarketDailyBarRepository;
import com.egx.core.repository.StockInstrumentRepository;

@Service
public class AllocationService {

    private static final int CURRENCY_SCALE = 4;
    private static final BigDecimal ZERO_MONEY = BigDecimal.ZERO.setScale(CURRENCY_SCALE, RoundingMode.HALF_DOWN);

    private final AllocationExecutionRepository allocationExecutionRepository;
    private final MarketDailyBarRepository marketDailyBarRepository;
    private final StockInstrumentRepository stockInstrumentRepository;
    private final WalletService walletService;

    public AllocationService(
            AllocationExecutionRepository allocationExecutionRepository,
            MarketDailyBarRepository marketDailyBarRepository,
            StockInstrumentRepository stockInstrumentRepository,
            WalletService walletService
    ) {
        this.allocationExecutionRepository = allocationExecutionRepository;
        this.marketDailyBarRepository = marketDailyBarRepository;
        this.stockInstrumentRepository = stockInstrumentRepository;
        this.walletService = walletService;
    }

    @Transactional
    public AllocationResult allocate(
            Long userId,
            Long portfolioRunId,
            BigDecimal investableBudget,
            List<PortfolioTarget> targets
    ) {
        BigDecimal normalizedInvestable = money(investableBudget);
        BigDecimal executedTotal = ZERO_MONEY;
        LocalDate settlementDate = addBusinessDays(LocalDate.now(), 2);

        List<AllocationExecution> executions = new ArrayList<>();
        for (PortfolioTarget target : targets) {
            BigDecimal targetAmount = money(target.getTargetAmountEgp());
            BigDecimal executablePrice = resolveExecutablePrice(target.getStockId());

            BigDecimal priceSnapshot = ZERO_MONEY;
            long wholeShares = 0L;
            BigDecimal executedAmount = ZERO_MONEY;
            BigDecimal residualComponent = targetAmount;

            if (executablePrice != null) {
                priceSnapshot = money(executablePrice);
                BigDecimal exactShares = targetAmount.divide(priceSnapshot, 10, RoundingMode.HALF_DOWN);
                BigDecimal flooredShares = exactShares.setScale(0, RoundingMode.FLOOR);
                wholeShares = flooredShares.longValue();

                executedAmount = money(priceSnapshot.multiply(BigDecimal.valueOf(wholeShares)));
                residualComponent = money(targetAmount.subtract(executedAmount));
                if (residualComponent.compareTo(BigDecimal.ZERO) < 0) {
                    residualComponent = ZERO_MONEY;
                }
            }

            AllocationExecution execution = new AllocationExecution();
            execution.setPortfolioRunId(portfolioRunId);
            execution.setStockId(target.getStockId());
            execution.setPriceSnapshot(priceSnapshot);
            execution.setTargetAmountEgp(targetAmount);
            execution.setExecutedShares(wholeShares);
            execution.setExecutedAmountEgp(executedAmount);
            execution.setResidualComponentEgp(residualComponent);
            execution.setSettlementDate(settlementDate);
            execution.setSettlementStatus(SettlementStatus.PENDING);
            execution.setCreatedAt(LocalDateTime.now());
            executions.add(execution);

            executedTotal = money(executedTotal.add(executedAmount));
        }

        List<AllocationExecution> savedExecutions = allocationExecutionRepository.saveAll(executions);

        BigDecimal residualTotal = money(normalizedInvestable.subtract(executedTotal));
        if (residualTotal.compareTo(BigDecimal.ZERO) < 0) {
            residualTotal = ZERO_MONEY;
        }

        BigDecimal creditedResidual = walletService.creditResidual(userId, residualTotal, portfolioRunId);
        return new AllocationResult(savedExecutions, creditedResidual);
    }

    private BigDecimal resolveExecutablePrice(Long stockId) {
        BigDecimal marketClose = marketDailyBarRepository
                .findTopByStockIdOrderByTradeDateDesc(stockId)
                .map(MarketDailyBar::getClosePrice)
                .map(this::normalizePositivePrice)
                .orElse(null);

        if (marketClose != null) {
            return marketClose;
        }

        return stockInstrumentRepository
                .findById(stockId)
                .map(StockInstrument::getLastPrice)
                .map(this::normalizePositivePrice)
                .orElse(null);
    }

    private BigDecimal normalizePositivePrice(BigDecimal value) {
        if (value == null || value.compareTo(BigDecimal.ZERO) <= 0) {
            return null;
        }

        return money(value);
    }

    private LocalDate addBusinessDays(LocalDate from, int businessDays) {
        LocalDate cursor = from;
        int added = 0;

        while (added < businessDays) {
            cursor = cursor.plusDays(1);
            switch (cursor.getDayOfWeek()) {
                case FRIDAY, SATURDAY -> {
                }
                default -> added++;
            }
        }

        return cursor;
    }

    private BigDecimal money(BigDecimal amount) {
        return amount.setScale(CURRENCY_SCALE, RoundingMode.HALF_DOWN);
    }

    public record AllocationResult(
            List<AllocationExecution> executions,
            BigDecimal residualReturned
    ) {
    }
}
