package com.egx.core.controller;

import java.io.IOException;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.security.core.Authentication;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import com.egx.core.domain.AllocationExecution;
import com.egx.core.domain.PortfolioRun;
import com.egx.core.domain.TradeOrder;
import com.egx.core.domain.WalletLedgerEntry;
import com.egx.core.domain.enums.LedgerEntryType;
import com.egx.core.domain.enums.PortfolioRunStatus;
import com.egx.core.domain.enums.RiskLevel;
import com.egx.core.repository.AiPredictionAuditRepository;
import com.egx.core.repository.AllocationExecutionRepository;
import com.egx.core.repository.PortfolioRunRepository;
import com.egx.core.repository.TradeOrderRepository;
import com.egx.core.repository.WalletLedgerEntryRepository;
import com.egx.core.service.PortfolioService;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import jakarta.validation.constraints.Positive;

@RestController
@Validated
public class PortfolioController {

    private final PortfolioService portfolioService;
    private final PortfolioRunRepository portfolioRunRepository;
    private final AllocationExecutionRepository allocationExecutionRepository;
    private final TradeOrderRepository tradeOrderRepository;
    private final WalletLedgerEntryRepository walletLedgerEntryRepository;
    private final AiPredictionAuditRepository aiPredictionAuditRepository;
    private final ObjectMapper objectMapper;

    public PortfolioController(
            PortfolioService portfolioService,
            PortfolioRunRepository portfolioRunRepository,
            AllocationExecutionRepository allocationExecutionRepository,
            TradeOrderRepository tradeOrderRepository,
            WalletLedgerEntryRepository walletLedgerEntryRepository,
            AiPredictionAuditRepository aiPredictionAuditRepository,
            ObjectMapper objectMapper
    ) {
        this.portfolioService = portfolioService;
        this.portfolioRunRepository = portfolioRunRepository;
        this.allocationExecutionRepository = allocationExecutionRepository;
        this.tradeOrderRepository = tradeOrderRepository;
        this.walletLedgerEntryRepository = walletLedgerEntryRepository;
        this.aiPredictionAuditRepository = aiPredictionAuditRepository;
        this.objectMapper = objectMapper;
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
            .findFirstByUserIdAndRunStatusInOrderByGeneratedAtDescIdDesc(
                    userId,
                    List.of(PortfolioRunStatus.COMPLETED, PortfolioRunStatus.PARTIAL)
            )
            .orElse(null);

        if (run == null) {
            return emptyPortfolioResponse();
        }

        return mapStoredPortfolio(run, authenticatedUserId);
    }

    @GetMapping({
            "/users/me/portfolio/latest",
            "/api/core/users/me/portfolio/latest",
            "/users/me/portfolio",
            "/api/core/users/me/portfolio"
    })
    public PortfolioResponse getLatestPortfolioForAuthenticatedUser(Authentication authentication) {
        Long authenticatedUserId = resolveUserId(authentication);

        PortfolioRun run = portfolioRunRepository
                .findFirstByUserIdAndRunStatusInOrderByGeneratedAtDescIdDesc(
                        authenticatedUserId,
                        List.of(PortfolioRunStatus.COMPLETED, PortfolioRunStatus.PARTIAL)
                )
                .orElse(null);

        if (run == null) {
            return emptyPortfolioResponse();
        }

        return mapStoredPortfolio(run, authenticatedUserId);
    }

    private PortfolioResponse emptyPortfolioResponse() {
        return new PortfolioResponse(
                null,
                "NO_PORTFOLIO",
                null,
                BigDecimal.ZERO,
                BigDecimal.ZERO,
                BigDecimal.ZERO,
                BigDecimal.ZERO,
                BigDecimal.ZERO,
                null,
                null,
                null,
                null,
                null,
                null,
                List.of(),
                List.of(),
                List.of()
        );
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
        AiResponseSnapshot aiSnapshot = loadAiResponseSnapshot(run.getId());

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
                aiSnapshot.expectedReturn(),
                aiSnapshot.expectedVolatility(),
                aiSnapshot.predictedReturn(),
                aiSnapshot.confidenceScore(),
                aiSnapshot.modelAccuracy(),
                aiSnapshot.recommendations(),
                allocationResponses,
                orderResponses
        );
    }

    private AiResponseSnapshot loadAiResponseSnapshot(Long portfolioRunId) {
        return aiPredictionAuditRepository
                .findTopByPortfolioRunIdOrderByCreatedAtDesc(portfolioRunId)
                .map(audit -> parseAiResponseSnapshot(audit.getResponseJson()))
                .orElseGet(AiResponseSnapshot::empty);
    }

    private AiResponseSnapshot parseAiResponseSnapshot(String responseJson) {
        if (responseJson == null || responseJson.isBlank()) {
            return AiResponseSnapshot.empty();
        }

        try {
            JsonNode root = objectMapper.readTree(responseJson);

            return new AiResponseSnapshot(
                    readDecimal(root, "expectedReturn", "expected_return"),
                    readDecimal(root, "expectedVolatility", "expected_volatility"),
                    readDecimal(root, "predictedReturn", "predicted_return"),
                    readDecimal(root, "confidenceScore", "confidence_score"),
                    readDecimal(root, "modelAccuracy", "model_accuracy"),
                    readRecommendations(root)
            );
        } catch (IOException | RuntimeException ex) {
            return AiResponseSnapshot.empty();
        }
    }

    private List<RecommendationResponse> readRecommendations(JsonNode root) {
        JsonNode items = root.get("recommendations");
        if (items == null || !items.isArray()) {
            return List.of();
        }

        List<RecommendationResponse> recommendations = new ArrayList<>();
        for (JsonNode item : items) {
            if (item == null || item.isNull()) {
                continue;
            }

            recommendations.add(
                    new RecommendationResponse(
                            readText(item, "symbol"),
                            readText(item, "action"),
                            readText(item, "reason"),
                            readDecimal(item, "predictedReturn5d", "predicted_return_5d"),
                            readDecimal(item, "confidenceScore", "confidence_score")
                    )
            );
        }

        return recommendations;
    }

    private BigDecimal readDecimal(JsonNode node, String... keys) {
        for (String key : keys) {
            JsonNode valueNode = node.get(key);
            if (valueNode == null || valueNode.isNull()) {
                continue;
            }

            if (valueNode.isNumber()) {
                return valueNode.decimalValue();
            }

            if (valueNode.isTextual()) {
                String textValue = valueNode.asText().trim();
                if (textValue.isEmpty()) {
                    continue;
                }

                try {
                    return new BigDecimal(textValue);
                } catch (NumberFormatException ex) {
                    return null;
                }
            }
        }

        return null;
    }

    private String readText(JsonNode node, String... keys) {
        for (String key : keys) {
            JsonNode valueNode = node.get(key);
            if (valueNode == null || valueNode.isNull()) {
                continue;
            }

            String value = valueNode.asText("").trim();
            if (!value.isEmpty()) {
                return value;
            }
        }

        return null;
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
            BigDecimal expectedReturn,
            BigDecimal expectedVolatility,
            BigDecimal predictedReturn,
            BigDecimal confidenceScore,
            BigDecimal modelAccuracy,
            List<RecommendationResponse> recommendations,
            List<AllocationResponse> allocations,
            List<OrderResponse> orders
    ) {
    }

        public record RecommendationResponse(
            String symbol,
            String action,
            String reason,
            BigDecimal predictedReturn5d,
            BigDecimal confidenceScore
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

    private record AiResponseSnapshot(
            BigDecimal expectedReturn,
            BigDecimal expectedVolatility,
            BigDecimal predictedReturn,
            BigDecimal confidenceScore,
            BigDecimal modelAccuracy,
            List<RecommendationResponse> recommendations
    ) {
        private static AiResponseSnapshot empty() {
            return new AiResponseSnapshot(null, null, null, null, null, List.of());
        }
    }
}
