package com.egx.core.service;

import com.egx.core.domain.AllocationExecution;
import com.egx.core.domain.MarketDailyBar;
import com.egx.core.domain.PortfolioTarget;
import com.egx.core.domain.enums.SettlementStatus;
import com.egx.core.repository.AllocationExecutionRepository;
import com.egx.core.repository.MarketDailyBarRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

@Service
public class AllocationService {

    private static final int CURRENCY_SCALE = 4;
    private static final BigDecimal FALLBACK_PRICE_EGP = new BigDecimal("100.0000");

    private final AllocationExecutionRepository allocationExecutionRepository;
    private final MarketDailyBarRepository marketDailyBarRepository;
    private final WalletService walletService;

    public AllocationService(
            AllocationExecutionRepository allocationExecutionRepository,
            MarketDailyBarRepository marketDailyBarRepository,
            WalletService walletService
    ) {
        this.allocationExecutionRepository = allocationExecutionRepository;
        this.marketDailyBarRepository = marketDailyBarRepository;
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
        BigDecimal executedTotal = BigDecimal.ZERO.setScale(CURRENCY_SCALE, RoundingMode.HALF_DOWN);
        LocalDate settlementDate = addBusinessDays(LocalDate.now(), 2);

        List<AllocationExecution> executions = new ArrayList<>();
        for (PortfolioTarget target : targets) {
            MarketDailyBar latestBar = marketDailyBarRepository
                .findTopByStockIdOrderByTradeDateDesc(target.getStockId())
                .orElse(null);

            BigDecimal priceSnapshot = latestBar == null
                ? FALLBACK_PRICE_EGP
                : money(latestBar.getClosePrice());
            if (priceSnapshot.compareTo(BigDecimal.ZERO) <= 0) {
            priceSnapshot = FALLBACK_PRICE_EGP;
            }

            BigDecimal targetAmount = money(target.getTargetAmountEgp());
            BigDecimal exactShares = targetAmount.divide(priceSnapshot, 10, RoundingMode.HALF_DOWN);
            BigDecimal flooredShares = exactShares.setScale(0, RoundingMode.FLOOR);
            long wholeShares = flooredShares.longValue();

            BigDecimal executedAmount = money(priceSnapshot.multiply(BigDecimal.valueOf(wholeShares)));
            BigDecimal residualComponent = money(targetAmount.subtract(executedAmount));
            if (residualComponent.compareTo(BigDecimal.ZERO) < 0) {
                residualComponent = BigDecimal.ZERO.setScale(CURRENCY_SCALE, RoundingMode.HALF_DOWN);
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
            residualTotal = BigDecimal.ZERO.setScale(CURRENCY_SCALE, RoundingMode.HALF_DOWN);
        }

        BigDecimal creditedResidual = walletService.creditResidual(userId, residualTotal, portfolioRunId);
        return new AllocationResult(savedExecutions, creditedResidual);
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
