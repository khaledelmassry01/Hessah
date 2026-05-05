package com.egx.core.service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

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
import com.egx.core.domain.StopRule;
import com.egx.core.domain.TradeOrder;
import com.egx.core.domain.Wallet;
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
import com.egx.core.repository.StopRuleRepository;
import com.egx.core.repository.SubscriptionRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

@Service
public class PortfolioService {

    private static final int CURRENCY_SCALE = 4;
    private static final int WEIGHT_SCALE = 8;
    private static final int SYMBOL_MAX_LENGTH = 16;
    private static final String EGX_SUFFIX = ".CA";
    private static final String DEFAULT_SECTOR_CODE = "FIN_SERV";
    private static final BigDecimal FEE_MULTIPLIER = new BigDecimal("0.995");
    private static final BigDecimal SMART_MIN_CONFIDENCE_THRESHOLD = new BigDecimal("0.55");

    // Risk-based max sector weights (P1-01 fix)
    private static final BigDecimal MAX_SECTOR_WEIGHT_LOW = new BigDecimal("0.20");
    private static final BigDecimal MAX_SECTOR_WEIGHT_MEDIUM = new BigDecimal("0.30");
    private static final BigDecimal MAX_SECTOR_WEIGHT_HIGH = new BigDecimal("0.40");

    // Risk-based stop-loss / take-profit percentages (P1-04 fix)
    private static final BigDecimal SL_LOW = new BigDecimal("0.030");   // 3%
    private static final BigDecimal TP_LOW = new BigDecimal("0.060");   // 6%
    private static final BigDecimal SL_MEDIUM = new BigDecimal("0.050"); // 5%
    private static final BigDecimal TP_MEDIUM = new BigDecimal("0.100"); // 10%
    private static final BigDecimal SL_HIGH = new BigDecimal("0.080");   // 8%
    private static final BigDecimal TP_HIGH = new BigDecimal("0.150");   // 15%

    private final WalletService walletService;
    private final SubscriptionRepository subscriptionRepository;
    private final PortfolioRunRepository portfolioRunRepository;
    private final PortfolioTargetRepository portfolioTargetRepository;
    private final StockInstrumentRepository stockInstrumentRepository;
    private final AiClient aiClient;
    private final AiPredictionAuditRepository aiPredictionAuditRepository;
    private final StopRuleRepository stopRuleRepository;
    private final AllocationService allocationService;
    private final OrderService orderService;
    private final PortfolioOptimizer portfolioOptimizer;
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
            StopRuleRepository stopRuleRepository,
            AllocationService allocationService,
            OrderService orderService,
            PortfolioOptimizer portfolioOptimizer,
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
        this.stopRuleRepository = stopRuleRepository;
        this.allocationService = allocationService;
        this.orderService = orderService;
        this.portfolioOptimizer = portfolioOptimizer;
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
            BigDecimal normalizedRequestedAmount = money(requestedAmount);
            portfolioRun.setRequestedAmountEgp(normalizedRequestedAmount);
            portfolioRun.setFeeBufferRate(new BigDecimal("0.00500"));
            portfolioRun.setInvestableBudgetEgp(BigDecimal.ZERO.setScale(CURRENCY_SCALE, RoundingMode.HALF_DOWN));
            portfolioRun.setRunStatus(PortfolioRunStatus.PENDING);
            portfolioRun.setGeneratedAt(LocalDateTime.now());
            portfolioRun = portfolioRunRepository.save(portfolioRun);

            Wallet wallet = walletService.getWalletByUserId(userId);
            BigDecimal availableBalance = wallet.getAvailableBalance() == null
                    ? BigDecimal.ZERO
                    : wallet.getAvailableBalance();

            boolean usingVirtualTestingBalance = availableBalance.compareTo(normalizedRequestedAmount) < 0;
            WalletService.FeeBufferDeduction fee;

            if (usingVirtualTestingBalance) {
                BigDecimal virtualRequestedAmount = normalizedRequestedAmount;
                BigDecimal virtualInvestableBudget = money(virtualRequestedAmount.multiply(FEE_MULTIPLIER));
                BigDecimal virtualFeeAmount = money(virtualRequestedAmount.subtract(virtualInvestableBudget));
                fee = new WalletService.FeeBufferDeduction(
                        virtualRequestedAmount,
                        virtualInvestableBudget,
                        virtualFeeAmount
                );
            } else {
                fee = walletService.deductFeeBuffer(userId, normalizedRequestedAmount, portfolioRun.getId());
            }

            portfolioRun.setInvestableBudgetEgp(fee.investableBudget());

            AiPredictionRequest aiRequest = buildAiRequest(portfolioRun, tier);
            AiPredictionResponse aiResponse = aiClient.predict(aiRequest);
            persistAiAudit(portfolioRun.getId(), aiRequest, aiResponse);

            String aiStatus = aiResponse.getStatus() == null ? "FAILED" : aiResponse.getStatus().toUpperCase();
            if ("FAILED".equals(aiStatus)) {
                portfolioRun.setRunStatus(PortfolioRunStatus.FAILED);
                portfolioRunRepository.save(portfolioRun);
                if (!usingVirtualTestingBalance) {
                    walletService.creditResidual(userId, fee.investableBudget(), portfolioRun.getId());
                }
                throw new AiIntegrationException("AI engine returned FAILED status for request " + portfolioRun.getRequestUuid());
            }

            BigDecimal maxSectorWeight = switch (riskLevel) {
                case LOW -> MAX_SECTOR_WEIGHT_LOW;
                case MEDIUM -> MAX_SECTOR_WEIGHT_MEDIUM;
                case HIGH -> MAX_SECTOR_WEIGHT_HIGH;
            };
            PortfolioOptimizer.OptimizationResult optimizationResult = portfolioOptimizer.optimize(
                    aiResponse.getAllocations(),
                    maxSectorWeight,
                    SMART_MIN_CONFIDENCE_THRESHOLD
            );
            aiResponse.setAllocations(optimizationResult.allocations());
            if (aiResponse.getWarnings() == null) {
                aiResponse.setWarnings(new ArrayList<>());
            }
            aiResponse.getWarnings().addAll(optimizationResult.warnings());
            if (optimizationResult.cashWeight().compareTo(BigDecimal.ZERO) > 0) {
                aiStatus = "PARTIAL";
            }

            List<PortfolioTarget> targets = persistTargets(portfolioRun, fee.investableBudget(), aiResponse.getAllocations(), riskLevel);
            AllocationService.AllocationResult allocationResult = allocationService.allocate(
                    userId,
                    portfolioRun.getId(),
                    fee.investableBudget(),
                    targets,
                    !usingVirtualTestingBalance
            );

            List<TradeOrder> orders = orderService.createPendingOrdersFromAllocations(
                    userId,
                    portfolioRun.getId(),
                    allocationResult.executions()
            );

            boolean hasUnpricedAllocations = allocationResult.executions().stream()
                    .anyMatch(execution -> execution.getPriceSnapshot() == null
                            || execution.getPriceSnapshot().compareTo(BigDecimal.ZERO) <= 0);

            if ("PARTIAL".equals(aiStatus) || hasUnpricedAllocations) {
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
            successDetails.put("usedVirtualTestingBalance", usingVirtualTestingBalance);
            securityAuditService.log("PORTFOLIO_GENERATION", userId, "SUCCESS", successDetails);

            List<StopRule> stopRules = new ArrayList<>();
            if (allocationResult != null && allocationResult.executions() != null) {
                for (AllocationExecution exec : allocationResult.executions()) {
                    if (exec != null && exec.getExecutedShares() != null && exec.getExecutedShares() > 0) {
                        StopRule rule = new StopRule();
                        rule.setUserId(userId);
                        rule.setStockId(exec.getStockId());
                        rule.setPortfolioRunId(portfolioRun.getId());
                        // Dynamic SL/TP based on risk level (P1-04 fix)
                        BigDecimal[] slTp = resolveStopLossTakeProfit(riskLevel);
                        rule.setStopLossPct(slTp[0]);
                        rule.setTakeProfitPct(slTp[1]);
                        rule.setIsActive(true);
                        rule.setCreatedAt(LocalDateTime.now());
                        rule.setUpdatedAt(LocalDateTime.now());
                        stopRules.add(rule);
                    }
                }
            }
            
            if (!stopRules.isEmpty()) {
                stopRuleRepository.saveAll(stopRules);
                stopRuleRepository.flush(); // Ensure it hits the DB before transaction ends
            }

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
            case LOW -> MAX_SECTOR_WEIGHT_LOW;
            case MEDIUM -> MAX_SECTOR_WEIGHT_MEDIUM;
            case HIGH -> MAX_SECTOR_WEIGHT_HIGH;
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

            StockInstrument stock = resolveInstrumentForAllocation(item.getSymbol());

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
            String sectorCode = stock.getSectorCode();
            if (sectorCode == null || sectorCode.isBlank()) {
                sectorCode = DEFAULT_SECTOR_CODE;
            }
            target.setSectorCode(sectorCode);
            target.setConstraintFlagsJson(
                    "{\"risk_level\":\"" + riskLevel.name() + "\",\"max_sector_weight\":0.30,\"max_adv30_participation\":0.05,\"exclude_suspended\":true}"
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
        String normalizedSymbol = normalizeSymbol(symbol);
        if (normalizedSymbol == null) {
            throw new IllegalStateException("AI response contains a blank symbol");
        }

        final String symbolKey = normalizedSymbol;

        StockInstrument existing = findBySymbolAliases(symbolKey);
        if (existing != null) {
            if (!symbolKey.equals(existing.getSymbol())) {
                existing.setSymbol(symbolKey);
                existing.setUpdatedAt(LocalDateTime.now());
                return stockInstrumentRepository.save(existing);
            }
            return existing;
        }

        return stockInstrumentRepository.findBySymbol(symbolKey)
                .orElseGet(() -> {
                    LocalDateTime now = LocalDateTime.now();

                    StockInstrument synthetic = new StockInstrument();
                    synthetic.setSymbol(symbolKey);
                    synthetic.setName(symbolKey + " Auto-Registered");
                    // Note: sector is now a relationship to SectorReference (5NF compliance)
                    // Set sector via relationship lookup in service or use default
                    synthetic.setIsSuspended(false);
                    synthetic.setCreatedAt(now);
                    synthetic.setUpdatedAt(now);

                    return stockInstrumentRepository.save(synthetic);
                });
    }

    private StockInstrument resolveInstrumentForAllocation(String symbol) {
        String canonicalSymbol = normalizeSymbol(symbol);
        if (canonicalSymbol == null) {
            throw new IllegalStateException("AI response contains a blank symbol");
        }

        StockInstrument stock = findBySymbolAliases(canonicalSymbol);
        if (stock == null) {
            return autoRegisterInstrument(canonicalSymbol);
        }

        if (!canonicalSymbol.equals(stock.getSymbol())) {
            stock.setSymbol(canonicalSymbol);
            stock.setUpdatedAt(LocalDateTime.now());
            stock = stockInstrumentRepository.save(stock);
        }

        return stock;
    }

    private StockInstrument findBySymbolAliases(String canonicalSymbol) {
        StockInstrument stock = stockInstrumentRepository.findBySymbol(canonicalSymbol).orElse(null);
        if (stock != null) {
            return stock;
        }

        if (!canonicalSymbol.endsWith(EGX_SUFFIX) || canonicalSymbol.length() <= EGX_SUFFIX.length()) {
            return null;
        }

        String legacySymbol = canonicalSymbol.substring(0, canonicalSymbol.length() - EGX_SUFFIX.length());
        return stockInstrumentRepository.findBySymbol(legacySymbol).orElse(null);
    }

    private String normalizeSymbol(String symbol) {
        if (symbol == null || symbol.isBlank()) {
            return null;
        }

        String normalized = symbol.trim().toUpperCase(Locale.ROOT);
        if (normalized.contains(":")) {
            normalized = normalized.substring(normalized.lastIndexOf(':') + 1);
        }

        normalized = normalized.replaceAll("[^A-Z0-9._-]", "");
        if (normalized.isBlank()) {
            return null;
        }

        if (normalized.endsWith(EGX_SUFFIX)) {
            return normalized.length() <= SYMBOL_MAX_LENGTH
                    ? normalized
                    : normalized.substring(0, SYMBOL_MAX_LENGTH);
        }

        if (normalized.contains(".")) {
            normalized = normalized.substring(0, normalized.indexOf('.'));
        }

        normalized = normalized.replaceAll("[^A-Z0-9_-]", "");
        if (normalized.isBlank()) {
            return null;
        }

        String canonical = normalized + EGX_SUFFIX;
        return canonical.length() <= SYMBOL_MAX_LENGTH
                ? canonical
                : canonical.substring(0, SYMBOL_MAX_LENGTH);
    }

    public record PortfolioExecutionResult(
            PortfolioRun portfolioRun,
            List<AllocationExecution> allocations,
            List<TradeOrder> orders,
            BigDecimal residualReturned
    ) {
    }

    /**
     * Resolves stop-loss and take-profit percentages based on risk level.
     * LOW risk: 3% SL / 6% TP
     * MEDIUM risk: 5% SL / 10% TP
     * HIGH risk: 8% SL / 15% TP
     */
    private BigDecimal[] resolveStopLossTakeProfit(RiskLevel riskLevel) {
        return switch (riskLevel) {
            case LOW -> new BigDecimal[]{SL_LOW, TP_LOW};
            case MEDIUM -> new BigDecimal[]{SL_MEDIUM, TP_MEDIUM};
            case HIGH -> new BigDecimal[]{SL_HIGH, TP_HIGH};
        };
    }
}
