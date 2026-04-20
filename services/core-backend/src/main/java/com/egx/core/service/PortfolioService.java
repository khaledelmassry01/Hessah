package com.egx.core.service;

import com.egx.core.client.AiClient;
import com.egx.core.client.dto.AiAllocationItem;
import com.egx.core.client.dto.AiConstraintsPayload;
import com.egx.core.client.dto.AiPredictionRequest;
import com.egx.core.client.dto.AiPredictionResponse;
import com.egx.core.domain.AiPredictionAudit;
import com.egx.core.domain.AllocationExecution;
import com.egx.core.domain.PortfolioRun;
import com.egx.core.domain.PortfolioTarget;
import com.egx.core.domain.StockInstrument;
import com.egx.core.domain.TradeOrder;
import com.egx.core.domain.enums.PortfolioRunStatus;
import com.egx.core.domain.enums.RiskLevel;
import com.egx.core.domain.enums.SubscriptionStatus;
import com.egx.core.domain.enums.SubscriptionTier;
import com.egx.core.exception.AiIntegrationException;
import com.egx.core.exception.TierAccessDeniedException;
import com.egx.core.repository.AiPredictionAuditRepository;
import com.egx.core.repository.PortfolioRunRepository;
import com.egx.core.repository.PortfolioTargetRepository;
import com.egx.core.repository.StockInstrumentRepository;
import com.egx.core.repository.SubscriptionRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Service
public class PortfolioService {

    private static final int CURRENCY_SCALE = 4;
    private static final int WEIGHT_SCALE = 8;
    private static final String DEFAULT_SECTOR_CODE = "FIN_SERV";
    private static final BigDecimal FALLBACK_LAST_PRICE = new BigDecimal("1.0000");

    private final WalletService walletService;
    private final SubscriptionRepository subscriptionRepository;
    private final PortfolioRunRepository portfolioRunRepository;
    private final PortfolioTargetRepository portfolioTargetRepository;
    private final StockInstrumentRepository stockInstrumentRepository;
    private final AiClient aiClient;
    private final AiPredictionAuditRepository aiPredictionAuditRepository;
    private final AllocationService allocationService;
    private final OrderService orderService;
    private final ObjectMapper objectMapper;
    private final SecurityAuditService securityAuditService;

    public PortfolioService(
            WalletService walletService,
            SubscriptionRepository subscriptionRepository,
            PortfolioRunRepository portfolioRunRepository,
            PortfolioTargetRepository portfolioTargetRepository,
            StockInstrumentRepository stockInstrumentRepository,
            AiClient aiClient,
            AiPredictionAuditRepository aiPredictionAuditRepository,
            AllocationService allocationService,
            OrderService orderService,
            ObjectMapper objectMapper,
            SecurityAuditService securityAuditService
    ) {
        this.walletService = walletService;
        this.subscriptionRepository = subscriptionRepository;
        this.portfolioRunRepository = portfolioRunRepository;
        this.portfolioTargetRepository = portfolioTargetRepository;
        this.stockInstrumentRepository = stockInstrumentRepository;
        this.aiClient = aiClient;
        this.aiPredictionAuditRepository = aiPredictionAuditRepository;
        this.allocationService = allocationService;
        this.orderService = orderService;
        this.objectMapper = objectMapper;
        this.securityAuditService = securityAuditService;
    }

    @Transactional
    public PortfolioExecutionResult generatePortfolio(Long userId, BigDecimal requestedAmount, RiskLevel riskLevel) {
        PortfolioRun portfolioRun = null;

        try {
            if (requestedAmount == null || requestedAmount.compareTo(BigDecimal.ZERO) <= 0) {
                throw new IllegalArgumentException("requestedAmount must be greater than zero");
            }

            SubscriptionTier tier = resolveTier(userId);
            enforceTierForRisk(tier, riskLevel);

            portfolioRun = new PortfolioRun();
            portfolioRun.setRequestUuid(UUID.randomUUID().toString());
            portfolioRun.setUserId(userId);
            portfolioRun.setRiskLevel(riskLevel);
            portfolioRun.setRequestedAmountEgp(money(requestedAmount));
            portfolioRun.setFeeBufferRate(new BigDecimal("0.00500"));
            portfolioRun.setInvestableBudgetEgp(BigDecimal.ZERO.setScale(CURRENCY_SCALE, RoundingMode.HALF_DOWN));
            portfolioRun.setRunStatus(PortfolioRunStatus.PENDING);
            portfolioRun.setGeneratedAt(LocalDateTime.now());
            portfolioRun = portfolioRunRepository.save(portfolioRun);

            WalletService.FeeBufferDeduction fee = walletService.deductFeeBuffer(userId, requestedAmount, portfolioRun.getId());
            portfolioRun.setInvestableBudgetEgp(fee.investableBudget());

            AiPredictionRequest aiRequest = buildAiRequest(portfolioRun, tier);
            AiPredictionResponse aiResponse = aiClient.predict(aiRequest);
            persistAiAudit(portfolioRun.getId(), aiRequest, aiResponse);

            String aiStatus = aiResponse.getStatus() == null ? "FAILED" : aiResponse.getStatus().toUpperCase();
            if ("FAILED".equals(aiStatus)) {
                portfolioRun.setRunStatus(PortfolioRunStatus.FAILED);
                portfolioRunRepository.save(portfolioRun);
                walletService.creditResidual(userId, fee.investableBudget(), portfolioRun.getId());
                throw new AiIntegrationException("AI engine returned FAILED status for request " + portfolioRun.getRequestUuid());
            }

            List<PortfolioTarget> targets = persistTargets(portfolioRun, fee.investableBudget(), aiResponse.getAllocations(), riskLevel);
            AllocationService.AllocationResult allocationResult = allocationService.allocate(
                    userId,
                    portfolioRun.getId(),
                    fee.investableBudget(),
                    targets
            );

            List<TradeOrder> orders = orderService.createPendingOrdersFromAllocations(
                    userId,
                    portfolioRun.getId(),
                    allocationResult.executions()
            );

            if ("PARTIAL".equals(aiStatus)) {
                portfolioRun.setRunStatus(PortfolioRunStatus.PARTIAL);
            } else {
                portfolioRun.setRunStatus(PortfolioRunStatus.COMPLETED);
            }
            portfolioRun.setModelVersion(aiResponse.getModelVersion());
            portfolioRunRepository.save(portfolioRun);

            Map<String, Object> successDetails = new LinkedHashMap<>();
            successDetails.put("runId", portfolioRun.getId());
            successDetails.put("riskLevel", riskLevel == null ? null : riskLevel.name());
            successDetails.put("requestedAmountEgp", requestedAmount);
            successDetails.put("status", portfolioRun.getRunStatus().name());
            securityAuditService.log("PORTFOLIO_GENERATION", userId, "SUCCESS", successDetails);

            return new PortfolioExecutionResult(
                    portfolioRun,
                    allocationResult.executions(),
                    orders,
                    allocationResult.residualReturned()
            );
        } catch (RuntimeException ex) {
            Map<String, Object> failureDetails = new LinkedHashMap<>();
            failureDetails.put("runId", portfolioRun == null ? null : portfolioRun.getId());
            failureDetails.put("riskLevel", riskLevel == null ? null : riskLevel.name());
            failureDetails.put("requestedAmountEgp", requestedAmount);
            failureDetails.put("reason", ex.getClass().getSimpleName());
            securityAuditService.log("PORTFOLIO_GENERATION", userId, "FAILED", failureDetails);
            throw ex;
        }
    }

    private SubscriptionTier resolveTier(Long userId) {
        boolean hasActivePremium = subscriptionRepository
                .findFirstByUserIdAndTierAndStatusOrderByStartedAtDesc(
                        userId,
                        SubscriptionTier.PREMIUM,
                        SubscriptionStatus.ACTIVE
                )
                .isPresent();

        return hasActivePremium ? SubscriptionTier.PREMIUM : SubscriptionTier.FREE;
    }

    private void enforceTierForRisk(SubscriptionTier tier, RiskLevel riskLevel) {
        if (tier == SubscriptionTier.FREE && riskLevel != RiskLevel.LOW) {
            throw new TierAccessDeniedException("FREE tier users can only request LOW risk portfolios");
        }
    }

    private AiPredictionRequest buildAiRequest(PortfolioRun portfolioRun, SubscriptionTier tier) {
        AiConstraintsPayload constraints = buildConstraints(portfolioRun.getRiskLevel());

        AiPredictionRequest request = new AiPredictionRequest();
        request.setRequestId(portfolioRun.getRequestUuid());
        request.setUserId(String.valueOf(portfolioRun.getUserId()));
        request.setAsOfDate(LocalDate.now());
        request.setBudgetEgp(money(portfolioRun.getInvestableBudgetEgp()));
        request.setRiskLevel(portfolioRun.getRiskLevel().name());
        request.setTier(tier.name());
        request.setConstraints(constraints);
        return request;
    }

    private AiConstraintsPayload buildConstraints(RiskLevel riskLevel) {
        AiConstraintsPayload constraints = new AiConstraintsPayload();
        constraints.setMaxSectorWeight(switch (riskLevel) {
            case LOW -> new BigDecimal("0.40");
            case MEDIUM -> new BigDecimal("0.40");
            case HIGH -> new BigDecimal("0.40");
        });
        constraints.setMaxAdv30Participation(new BigDecimal("0.05"));
        constraints.setExcludeSuspended(true);
        constraints.setAllowFractionalShares(false);
        return constraints;
    }

    private List<PortfolioTarget> persistTargets(
            PortfolioRun portfolioRun,
            BigDecimal investableBudget,
            List<AiAllocationItem> allocations,
            RiskLevel riskLevel
    ) {
        if (allocations == null) {
            return List.of();
        }

        List<PortfolioTarget> targets = new ArrayList<>();
        for (AiAllocationItem item : allocations) {
            if (item == null || item.getWeight() == null || item.getWeight().compareTo(BigDecimal.ZERO) <= 0) {
                continue;
            }

            StockInstrument stock = stockInstrumentRepository
                    .findBySymbol(item.getSymbol())
                    .orElseGet(() -> autoRegisterInstrument(item.getSymbol()));

            if (stock.getLastPrice() == null || stock.getLastPrice().compareTo(BigDecimal.ZERO) <= 0) {
                stock.setLastPrice(FALLBACK_LAST_PRICE);
                stock.setUpdatedAt(LocalDateTime.now());
                stock = stockInstrumentRepository.save(stock);
            }

            if (Boolean.TRUE.equals(stock.getIsSuspended())) {
                throw new IllegalStateException("AI response contains suspended stock: " + stock.getSymbol());
            }

            BigDecimal normalizedWeight = item.getWeight().setScale(WEIGHT_SCALE, RoundingMode.HALF_DOWN);
            BigDecimal targetAmount = money(investableBudget.multiply(normalizedWeight));

            PortfolioTarget target = new PortfolioTarget();
            target.setPortfolioRunId(portfolioRun.getId());
            target.setStockId(stock.getId());
            target.setTargetWeight(normalizedWeight);
            target.setTargetAmountEgp(targetAmount);
                // Use the stock instrument sector to keep FK integrity with sector_reference.
                target.setSectorCode(stock.getSectorCode());
            target.setConstraintFlagsJson(
                    "{\"risk_level\":\"" + riskLevel.name() + "\",\"max_sector_weight\":0.40,\"max_adv30_participation\":0.05,\"exclude_suspended\":true}"
            );
            targets.add(target);
        }

        return portfolioTargetRepository.saveAll(targets);
    }

    private void persistAiAudit(Long portfolioRunId, AiPredictionRequest request, AiPredictionResponse response) {
        AiPredictionAudit audit = new AiPredictionAudit();
        audit.setPortfolioRunId(portfolioRunId);
        audit.setRequestJson(writeJsonSafe(request));
        audit.setResponseJson(writeJsonSafe(response));
        audit.setCreatedAt(LocalDateTime.now());
        aiPredictionAuditRepository.save(audit);
    }

    private String writeJsonSafe(Object payload) {
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (JsonProcessingException ex) {
            return "{\"serialization_error\":\"" + ex.getMessage() + "\"}";
        }
    }

    private BigDecimal money(BigDecimal amount) {
        return amount.setScale(CURRENCY_SCALE, RoundingMode.HALF_DOWN);
    }

    private StockInstrument autoRegisterInstrument(String symbol) {
        if (symbol == null || symbol.isBlank()) {
            throw new IllegalStateException("AI response contains a blank symbol");
        }

        String normalizedSymbol = symbol.trim().toUpperCase();
        if (normalizedSymbol.length() > 16) {
            normalizedSymbol = normalizedSymbol.substring(0, 16);
        }

        final String symbolKey = normalizedSymbol;

        return stockInstrumentRepository.findBySymbol(symbolKey)
                .orElseGet(() -> {
                    LocalDateTime now = LocalDateTime.now();

                    StockInstrument synthetic = new StockInstrument();
                    synthetic.setSymbol(symbolKey);
                    synthetic.setName(symbolKey + " Auto-Registered");
                    synthetic.setSectorCode(DEFAULT_SECTOR_CODE);
                    synthetic.setIsSuspended(false);
                    synthetic.setCreatedAt(now);
                    synthetic.setUpdatedAt(now);

                    return stockInstrumentRepository.save(synthetic);
                });
    }

    public record PortfolioExecutionResult(
            PortfolioRun portfolioRun,
            List<AllocationExecution> allocations,
            List<TradeOrder> orders,
            BigDecimal residualReturned
    ) {
    }
}
