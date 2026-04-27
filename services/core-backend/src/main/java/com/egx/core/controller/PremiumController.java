package com.egx.core.controller;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import org.springframework.http.HttpStatus;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import com.egx.core.client.AiClient;
import com.egx.core.client.dto.AiBacktestRequest;
import com.egx.core.client.dto.AiBacktestResponse;
import com.egx.core.client.dto.AiConstraintsPayload;
import com.egx.core.domain.DailyAiSignal;
import com.egx.core.domain.PortfolioRun;
import com.egx.core.domain.SignalXaiReason;
import com.egx.core.domain.StockInstrument;
import com.egx.core.domain.StopRule;
import com.egx.core.domain.enums.RiskLevel;
import com.egx.core.domain.enums.SubscriptionTier;
import com.egx.core.repository.DailyAiSignalRepository;
import com.egx.core.repository.PortfolioRunRepository;
import com.egx.core.repository.SignalXaiReasonRepository;
import com.egx.core.repository.StockInstrumentRepository;
import com.egx.core.repository.StopRuleRepository;
import com.egx.core.service.PremiumAccessService;
import com.egx.core.service.TearSheetService;

import jakarta.validation.Valid;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotNull;

@RestController
@RequestMapping({"/premium", "/api/core/premium"})
@PreAuthorize("hasAnyRole('PRO', 'ADMIN')")
@Validated
public class PremiumController {

    private static final BigDecimal DEFAULT_MAX_SECTOR_WEIGHT = new BigDecimal("0.30");
    private static final BigDecimal DEFAULT_MAX_ADV30_PARTICIPATION = new BigDecimal("0.05");

    private final PremiumAccessService premiumAccessService;
    private final AiClient aiClient;
    private final StopRuleRepository stopRuleRepository;
    private final TearSheetService tearSheetService;
    private final PortfolioRunRepository portfolioRunRepository;
    private final StockInstrumentRepository stockInstrumentRepository;
    private final DailyAiSignalRepository dailyAiSignalRepository;
    private final SignalXaiReasonRepository signalXaiReasonRepository;

    public PremiumController(
            PremiumAccessService premiumAccessService,
            AiClient aiClient,
            StopRuleRepository stopRuleRepository,
            TearSheetService tearSheetService,
            PortfolioRunRepository portfolioRunRepository,
            StockInstrumentRepository stockInstrumentRepository,
            DailyAiSignalRepository dailyAiSignalRepository,
            SignalXaiReasonRepository signalXaiReasonRepository
    ) {
        this.premiumAccessService = premiumAccessService;
        this.aiClient = aiClient;
        this.stopRuleRepository = stopRuleRepository;
        this.tearSheetService = tearSheetService;
        this.portfolioRunRepository = portfolioRunRepository;
        this.stockInstrumentRepository = stockInstrumentRepository;
        this.dailyAiSignalRepository = dailyAiSignalRepository;
        this.signalXaiReasonRepository = signalXaiReasonRepository;
    }

    @PostMapping("/backtest")
    public AiBacktestResponse requestBacktest(@Valid @RequestBody BacktestRequest request) {
        premiumAccessService.assertPremium(request.userId());

        AiBacktestRequest aiRequest = new AiBacktestRequest();
        aiRequest.setRequestId(UUID.randomUUID().toString());
        aiRequest.setUserId(String.valueOf(request.userId()));
        aiRequest.setBudgetEgp(request.budgetEgp().setScale(4, RoundingMode.HALF_DOWN));
        aiRequest.setHistoricalDate(request.historicalDate());
        aiRequest.setRiskLevel(request.riskLevel().name());
        aiRequest.setTier(SubscriptionTier.PREMIUM.name());

        AiConstraintsPayload constraints = new AiConstraintsPayload();
        constraints.setMaxSectorWeight(orDefault(request.maxSectorWeight(), DEFAULT_MAX_SECTOR_WEIGHT));
        constraints.setMaxAdv30Participation(orDefault(request.maxAdv30Participation(), DEFAULT_MAX_ADV30_PARTICIPATION));
        constraints.setExcludeSuspended(request.excludeSuspended() == null || request.excludeSuspended());
        constraints.setAllowFractionalShares(request.allowFractionalShares() != null && request.allowFractionalShares());
        aiRequest.setConstraints(constraints);

        return aiClient.backtest(aiRequest);
    }

    @PostMapping("/stop-rules")
    public StopRuleResponse setStopRule(@Valid @RequestBody StopRuleRequest request) {
        premiumAccessService.assertPremium(request.userId());

        StopRule rule = new StopRule();
        rule.setUserId(request.userId());
        rule.setStockId(request.stockId());
        rule.setPortfolioRunId(request.portfolioRunId());
        rule.setStopLossPct(request.stopLossPct().setScale(3, RoundingMode.HALF_DOWN));
        rule.setTakeProfitPct(request.takeProfitPct().setScale(3, RoundingMode.HALF_DOWN));
        rule.setIsActive(request.isActive() == null || request.isActive());
        rule.setCreatedAt(LocalDateTime.now());
        rule.setUpdatedAt(LocalDateTime.now());

        StopRule saved = stopRuleRepository.save(rule);
        // Enrich with AI signal data for the response
        StockInstrument stock = stockInstrumentRepository.findById(saved.getStockId()).orElse(null);
        String symbol = stock != null ? stock.getSymbol() : null;
        DailyAiSignal signal = null;
        if (symbol != null) {
            signal = dailyAiSignalRepository.findLatestBySymbol(symbol).orElse(null);
        }

        return new StopRuleResponse(
                saved.getId(),
                saved.getUserId(),
                saved.getStockId(),
                symbol,
                saved.getPortfolioRunId(),
                saved.getStopLossPct(),
                saved.getTakeProfitPct(),
                saved.getIsActive(),
                signal != null ? signal.getConfidenceScore() : null,
                signal != null ? signal.getPredictedReturn5d() : null,
                signal != null ? signal.getAction() : "UNKNOWN",
                loadXaiReasons(signal)
        );
    }

    @GetMapping("/market-watch")
    public List<StopRuleResponse> listStopRules(Authentication authentication) {
        Long userId = resolveUserId(authentication);
        premiumAccessService.assertPremium(userId);

        return stopRuleRepository.findByUserIdOrderByUpdatedAtDesc(userId)
                .stream()
                .map(this::enrichStopRuleWithAiSignal)
                .toList();
    }

    private StopRuleResponse enrichStopRuleWithAiSignal(StopRule rule) {
        StockInstrument stock = stockInstrumentRepository.findById(rule.getStockId()).orElse(null);
        String symbol = stock != null ? stock.getSymbol() : null;

        // Fetch latest AI signal if available
        DailyAiSignal signal = null;
        if (symbol != null) {
            signal = dailyAiSignalRepository.findLatestBySymbol(symbol).orElse(null);
        }

        return new StopRuleResponse(
                rule.getId(),
                rule.getUserId(),
                rule.getStockId(),
                symbol,  // Include symbol instead of just stockId
                rule.getPortfolioRunId(),
                rule.getStopLossPct(),
                rule.getTakeProfitPct(),
                rule.getIsActive(),
                signal != null ? signal.getConfidenceScore() : null,
                signal != null ? signal.getPredictedReturn5d() : null,
                signal != null ? signal.getAction() : "UNKNOWN",
                loadXaiReasons(signal)
        );
    }

    private List<String> loadXaiReasons(DailyAiSignal signal) {
        if (signal == null || signal.getId() == null) {
            return List.of();
        }

        List<SignalXaiReason> reasons = signalXaiReasonRepository.findBySignalIdOrderByReasonOrderAsc(signal.getId());
        return reasons.stream()
                .map(SignalXaiReason::getReasonText)
                .filter(Objects::nonNull)
                .map(String::trim)
                .filter(value -> !value.isEmpty())
                .limit(3)
                .toList();
    }

    @GetMapping("/tear-sheet/{portfolioRunId}")
    public TearSheetService.TearSheetResponse getTearSheet(@PathVariable Long portfolioRunId) {
        PortfolioRun run = portfolioRunRepository.findById(portfolioRunId)
                .orElseThrow(() -> new IllegalArgumentException("Portfolio run not found: " + portfolioRunId));

        premiumAccessService.assertPremium(run.getUserId());
        return tearSheetService.generate(portfolioRunId);
    }

    private BigDecimal orDefault(BigDecimal value, BigDecimal defaultValue) {
        if (value == null) {
            return defaultValue;
        }
        return value;
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

    public record BacktestRequest(
            @NotNull Long userId,
            @NotNull @DecimalMin("0.01") BigDecimal budgetEgp,
            @NotNull LocalDate historicalDate,
            @NotNull RiskLevel riskLevel,
            BigDecimal maxSectorWeight,
            BigDecimal maxAdv30Participation,
            Boolean excludeSuspended,
            Boolean allowFractionalShares
    ) {
    }

    public record StopRuleRequest(
            @NotNull Long userId,
            @NotNull Long stockId,
            Long portfolioRunId,
            @NotNull @DecimalMin("0.0") BigDecimal stopLossPct,
            @NotNull @DecimalMin("0.0") BigDecimal takeProfitPct,
            Boolean isActive
    ) {
    }

    /**
     * Enriched Stop Rule Response with AI signal data for Market Watch.
     */
    public record StopRuleResponse(
            Long id,
            Long userId,
            Long stockId,
            String symbol,              // Stock symbol (e.g., "COMI.CA")
            Long portfolioRunId,
            BigDecimal stopLossPct,
            BigDecimal takeProfitPct,
            Boolean isActive,
            BigDecimal confidenceScore, // AI confidence (0.0 - 1.0)
            BigDecimal predictedReturn5d, // 5-day predicted return
            String action,              // BUY, HOLD, SELL, PREVENTIVE_SELL, UNKNOWN
            List<String> xaiReasons     // Explainable AI reasons
    ) {
    }
}
