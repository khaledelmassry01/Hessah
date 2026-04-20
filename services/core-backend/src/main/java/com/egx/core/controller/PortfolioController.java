package com.egx.core.controller;

import com.egx.core.domain.AllocationExecution;
import com.egx.core.domain.PortfolioRun;
import com.egx.core.domain.TradeOrder;
import com.egx.core.domain.WalletLedgerEntry;
import com.egx.core.domain.enums.LedgerEntryType;
import com.egx.core.domain.enums.PortfolioRunStatus;
import com.egx.core.domain.enums.RiskLevel;
import com.egx.core.repository.AllocationExecutionRepository;
import com.egx.core.repository.PortfolioRunRepository;
import com.egx.core.repository.TradeOrderRepository;
import com.egx.core.repository.WalletLedgerEntryRepository;
import com.egx.core.service.PortfolioService;
import jakarta.validation.constraints.Positive;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.Authentication;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

@RestController
@Validated
public class PortfolioController {

    private final PortfolioService portfolioService;
    private final PortfolioRunRepository portfolioRunRepository;
    private final AllocationExecutionRepository allocationExecutionRepository;
    private final TradeOrderRepository tradeOrderRepository;
    private final WalletLedgerEntryRepository walletLedgerEntryRepository;

    public PortfolioController(
            PortfolioService portfolioService,
            PortfolioRunRepository portfolioRunRepository,
            AllocationExecutionRepository allocationExecutionRepository,
            TradeOrderRepository tradeOrderRepository,
            WalletLedgerEntryRepository walletLedgerEntryRepository
    ) {
        this.portfolioService = portfolioService;
        this.portfolioRunRepository = portfolioRunRepository;
        this.allocationExecutionRepository = allocationExecutionRepository;
        this.tradeOrderRepository = tradeOrderRepository;
        this.walletLedgerEntryRepository = walletLedgerEntryRepository;
    }

    @PostMapping({
            "/portfolio/generate",
            "/api/core/portfolio/generate",
            "/portfolios/generate",
            "/api/core/portfolios/generate",
            "/portfolio/allocate",
            "/api/core/portfolio/allocate",
            "/portfolio/request",
            "/api/core/portfolio/request",
            "/portfolio-runs",
            "/api/core/portfolio-runs",
            "/portfolios",
            "/api/core/portfolios"
    })
    public PortfolioResponse generatePortfolio(
            Authentication authentication,
            @RequestBody(required = false) Map<String, Object> payload
    ) {
        Long authenticatedUserId = resolveUserId(authentication);
        Long bodyUserId = extractLong(payload, "userId", "user_id");
        if (bodyUserId != null && !authenticatedUserId.equals(bodyUserId)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Forbidden for requested user");
        }

        BigDecimal requestedAmount = extractAmount(payload);
        RiskLevel riskLevel = extractRiskLevel(payload);

        PortfolioService.PortfolioExecutionResult result = portfolioService.generatePortfolio(
                authenticatedUserId,
                requestedAmount,
                riskLevel
        );

        PortfolioRun run = result.portfolioRun();
        BigDecimal feeBuffer = deriveFeeBuffer(run);
        BigDecimal residualReturned = defaultMoney(result.residualReturned());

        return mapPortfolioResponse(
                run,
                result.allocations(),
                result.orders(),
                feeBuffer,
                residualReturned
        );
    }

    @GetMapping({
            "/portfolio-runs/{runId}",
            "/api/core/portfolio-runs/{runId}",
            "/portfolios/{runId}",
            "/api/core/portfolios/{runId}",
            "/portfolio/{runId}",
            "/api/core/portfolio/{runId}"
    })
    public PortfolioResponse getPortfolioRun(
            Authentication authentication,
            @PathVariable @Positive Long runId
    ) {
        Long authenticatedUserId = resolveUserId(authentication);

        PortfolioRun run = portfolioRunRepository.findByIdAndUserId(runId, authenticatedUserId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Portfolio run not found"));

        return mapStoredPortfolio(run, authenticatedUserId);
    }

    @GetMapping({
            "/users/{userId}/portfolio/latest",
            "/api/core/users/{userId}/portfolio/latest",
            "/portfolio/latest/{userId}",
            "/api/core/portfolio/latest/{userId}",
            "/portfolio-runs/latest/{userId}",
            "/api/core/portfolio-runs/latest/{userId}",
            "/users/{userId}/portfolio",
            "/api/core/users/{userId}/portfolio"
    })
    public PortfolioResponse getLatestPortfolio(
            Authentication authentication,
            @PathVariable @Positive Long userId
    ) {
        Long authenticatedUserId = resolveUserId(authentication);
        assertOwnership(authenticatedUserId, userId);

        PortfolioRun run = portfolioRunRepository
            .findFirstByUserIdAndRunStatusOrderByGeneratedAtDescIdDesc(userId, PortfolioRunStatus.COMPLETED)
            .orElseThrow(() -> new ResponseStatusException(
                HttpStatus.NOT_FOUND,
                "No completed portfolio found for user: " + userId
            ));

        return mapStoredPortfolio(run, authenticatedUserId);
    }

    private PortfolioResponse mapStoredPortfolio(PortfolioRun run, Long userId) {
        List<AllocationExecution> allocations = allocationExecutionRepository.findByPortfolioRunId(run.getId());
        List<TradeOrder> orders = tradeOrderRepository.findByUserIdAndPortfolioRunId(userId, run.getId());

        BigDecimal feeBuffer = sumLedgerEntries(run.getId(), LedgerEntryType.FEE_BUFFER);
        if (feeBuffer.compareTo(BigDecimal.ZERO) == 0) {
            feeBuffer = deriveFeeBuffer(run);
        }

        BigDecimal residualReturned = sumLedgerEntries(run.getId(), LedgerEntryType.RESIDUAL_RETURN);
        if (residualReturned.compareTo(BigDecimal.ZERO) == 0) {
            residualReturned = allocations.stream()
                    .map(AllocationExecution::getResidualComponentEgp)
                    .map(this::defaultMoney)
                    .reduce(BigDecimal.ZERO, BigDecimal::add);
        }

        return mapPortfolioResponse(run, allocations, orders, feeBuffer, residualReturned);
    }

    private PortfolioResponse mapPortfolioResponse(
            PortfolioRun run,
            List<AllocationExecution> allocations,
            List<TradeOrder> orders,
            BigDecimal feeBuffer,
            BigDecimal residualReturned
    ) {
        List<AllocationResponse> allocationResponses = allocations.stream()
                .map(allocation -> new AllocationResponse(
                        allocation.getStockId(),
                        allocation.getTargetAmountEgp(),
                        allocation.getExecutedShares(),
                        allocation.getExecutedAmountEgp(),
                        allocation.getResidualComponentEgp(),
                        allocation.getPriceSnapshot(),
                        allocation.getSettlementStatus() == null ? null : allocation.getSettlementStatus().name()
                ))
                .toList();

        List<OrderResponse> orderResponses = orders.stream()
                .map(order -> new OrderResponse(
                        order.getStockId(),
                        order.getOrderQty(),
                        order.getFilledQty(),
                        order.getAvgFillPrice(),
                        order.getOrderStatus() == null ? null : order.getOrderStatus().name(),
                        order.getSettlementStatus() == null ? null : order.getSettlementStatus().name()
                ))
                .toList();

        return new PortfolioResponse(
                run.getId(),
                run.getRunStatus() == null ? null : run.getRunStatus().name(),
                run.getRiskLevel() == null ? null : run.getRiskLevel().name(),
                run.getRequestedAmountEgp(),
                run.getRequestedAmountEgp(),
                defaultMoney(feeBuffer),
                run.getInvestableBudgetEgp(),
                defaultMoney(residualReturned),
                run.getModelVersion(),
                allocationResponses,
                orderResponses
        );
    }

    private BigDecimal sumLedgerEntries(Long portfolioRunId, LedgerEntryType entryType) {
        return walletLedgerEntryRepository.findByReferenceIdAndEntryType(portfolioRunId, entryType)
                .stream()
                .map(WalletLedgerEntry::getAmount)
                .map(this::defaultMoney)
                .reduce(BigDecimal.ZERO, BigDecimal::add);
    }

    private BigDecimal deriveFeeBuffer(PortfolioRun run) {
        return defaultMoney(run.getRequestedAmountEgp())
                .subtract(defaultMoney(run.getInvestableBudgetEgp()));
    }

    private BigDecimal extractAmount(Map<String, Object> payload) {
        BigDecimal amount = toBigDecimal(
                firstValue(
                        payload,
                        "requestedAmountEgp",
                        "requested_amount_egp",
                        "amountEgp",
                        "amount_egp",
                        "amount"
                )
        );

        if (amount == null || amount.compareTo(BigDecimal.ZERO) <= 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "requested amount must be greater than zero");
        }

        return amount;
    }

    private RiskLevel extractRiskLevel(Map<String, Object> payload) {
        Object raw = firstValue(payload, "riskLevel", "risk_level");
        if (raw == null) {
            return RiskLevel.LOW;
        }

        String riskText = raw.toString().trim();
        if (riskText.isEmpty()) {
            return RiskLevel.LOW;
        }

        try {
            return RiskLevel.valueOf(riskText.toUpperCase());
        } catch (IllegalArgumentException ex) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid risk level: " + riskText);
        }
    }

    private Object firstValue(Map<String, Object> payload, String... keys) {
        if (payload == null) {
            return null;
        }

        for (String key : keys) {
            if (payload.containsKey(key)) {
                return payload.get(key);
            }
        }

        return null;
    }

    private Long extractLong(Map<String, Object> payload, String... keys) {
        BigDecimal value = toBigDecimal(firstValue(payload, keys));
        if (value == null) {
            return null;
        }
        return value.longValue();
    }

    private BigDecimal toBigDecimal(Object value) {
        if (value == null) {
            return null;
        }

        if (value instanceof BigDecimal decimalValue) {
            return decimalValue;
        }

        if (value instanceof Number numberValue) {
            return new BigDecimal(numberValue.toString());
        }

        if (value instanceof String stringValue) {
            String trimmed = stringValue.trim();
            if (trimmed.isEmpty()) {
                return null;
            }
            try {
                return new BigDecimal(trimmed);
            } catch (NumberFormatException ex) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid numeric value: " + stringValue);
            }
        }

        throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid numeric payload value type");
    }

    private BigDecimal defaultMoney(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
    }

    private Long resolveUserId(Authentication authentication) {
        if (authentication == null || !authentication.isAuthenticated()) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Authentication is required");
        }

        Object principal = authentication.getPrincipal();
        if (principal instanceof Number number) {
            return number.longValue();
        }

        throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Unable to resolve authenticated user");
    }

    private void assertOwnership(Long authenticatedUserId, Long requestedUserId) {
        if (!authenticatedUserId.equals(requestedUserId)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Forbidden for requested user");
        }
    }

    public record PortfolioResponse(
            Long portfolioRunId,
            String status,
            String riskLevel,
            BigDecimal requestedAmount,
            BigDecimal requestedAmountEgp,
            BigDecimal feeBuffer,
            BigDecimal investableBudget,
            BigDecimal residualReturned,
            String modelVersion,
            List<AllocationResponse> allocations,
            List<OrderResponse> orders
    ) {
    }

    public record AllocationResponse(
            Long stockId,
            BigDecimal targetAmountEgp,
            Long executedShares,
            BigDecimal executedAmountEgp,
            BigDecimal residualComponentEgp,
            BigDecimal priceSnapshot,
            String settlementStatus
    ) {
    }

    public record OrderResponse(
            Long stockId,
            Long orderQty,
            Long filledQty,
            BigDecimal avgFillPrice,
            String orderStatus,
            String settlementStatus
    ) {
    }
}
