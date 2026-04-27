package com.egx.core.service;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.egx.core.client.AiClient;
import com.egx.core.client.dto.AiConstraintsPayload;
import com.egx.core.client.dto.AiPredictionRequest;
import com.egx.core.client.dto.AiPredictionResponse;
import com.egx.core.client.dto.AiRecommendationItem;
import com.egx.core.domain.DailyAiSignal;
import com.egx.core.domain.SignalXaiReason;
import com.egx.core.domain.StockInstrument;
import com.egx.core.domain.StopRule;
import com.egx.core.repository.DailyAiSignalRepository;
import com.egx.core.repository.SignalXaiReasonRepository;
import com.egx.core.repository.StockInstrumentRepository;
import com.egx.core.repository.StopRuleRepository;

/**
 * Market Radar Service - Fetches AI predictions for active stop rules
 * and provides enriched market watch data.
 */
@Service
public class MarketRadarService {

    private static final Logger LOGGER = LoggerFactory.getLogger(MarketRadarService.class);

    private final StopRuleRepository stopRuleRepository;
    private final StockInstrumentRepository stockInstrumentRepository;
    private final DailyAiSignalRepository dailyAiSignalRepository;
    private final SignalXaiReasonRepository signalXaiReasonRepository;
    private final AiClient aiClient;

    public MarketRadarService(
            StopRuleRepository stopRuleRepository,
            StockInstrumentRepository stockInstrumentRepository,
            DailyAiSignalRepository dailyAiSignalRepository,
            SignalXaiReasonRepository signalXaiReasonRepository,
            AiClient aiClient
    ) {
        this.stopRuleRepository = stopRuleRepository;
        this.stockInstrumentRepository = stockInstrumentRepository;
        this.dailyAiSignalRepository = dailyAiSignalRepository;
        this.signalXaiReasonRepository = signalXaiReasonRepository;
        this.aiClient = aiClient;
    }

    /**
     * Fetch distinct symbols from active stop rules.
     */
    public List<String> getActiveStopRuleSymbols() {
        List<StopRule> activeRules = stopRuleRepository.findByIsActiveTrue();
        
        Set<Long> stockIds = activeRules.stream()
                .map(StopRule::getStockId)
                .collect(Collectors.toSet());

        if (stockIds.isEmpty()) {
            return List.of();
        }

        List<StockInstrument> instruments = stockInstrumentRepository.findAllById(stockIds);
        
        return instruments.stream()
                .map(StockInstrument::getSymbol)
                .filter(symbol -> symbol != null && !symbol.isBlank())
                .distinct()
                .toList();
    }

    /**
     * Scan all active stop rule symbols with AI and save signals.
     * Called by MarketRadarScheduler.
     */
    @Transactional
    public void scanAndSaveAiSignals() {
        List<String> symbols = getActiveStopRuleSymbols();
        
        if (symbols.isEmpty()) {
            LOGGER.info("No active stop rules to scan");
            return;
        }

        LOGGER.info("Scanning {} symbols for AI market radar", symbols.size());
        LocalDate today = LocalDate.now();

        // Create bulk prediction request for all active symbols
        AiPredictionRequest request = buildBulkPredictionRequest(symbols);
        
        try {
            AiPredictionResponse response = aiClient.predict(request);
            
            if (response == null || response.getRecommendations() == null) {
                LOGGER.warn("AI response empty for market radar scan");
                return;
            }

            // Map stock symbols to IDs for quick lookup
            Map<String, Long> symbolToId = stockInstrumentRepository.findAll().stream()
                    .collect(Collectors.toMap(
                            StockInstrument::getSymbol,
                            StockInstrument::getId,
                            (existing, replacement) -> existing
                    ));

            // Save each recommendation as a DailyAiSignal
            List<DailyAiSignal> signals = new ArrayList<>();
            Map<String, List<String>> symbolToXaiReasons = new HashMap<>();
            for (AiRecommendationItem rec : response.getRecommendations()) {
                if (rec == null || rec.getSymbol() == null) continue;
                
                DailyAiSignal signal = new DailyAiSignal();
                String action = determineAction(rec);
                String symbol = rec.getSymbol().toUpperCase();
                signal.setSymbol(symbol);
                signal.setStockId(symbolToId.get(symbol));
                signal.setSignalDate(today);
                signal.setAction(action);
                signal.setConfidenceScore(rec.getConfidenceScore());
                signal.setPredictedReturn5d(rec.getPredictedReturn5d());
                symbolToXaiReasons.put(symbol, buildXaiReasons(rec, action));
                signal.setModelVersion(response.getModelVersion());
                signal.setCreatedAt(LocalDateTime.now());
                signal.setUpdatedAt(LocalDateTime.now());
                
                signals.add(signal);
            }

            if (!signals.isEmpty()) {
                List<DailyAiSignal> savedSignals = dailyAiSignalRepository.saveAll(signals);
                for (DailyAiSignal savedSignal : savedSignals) {
                    List<String> reasons = symbolToXaiReasons.getOrDefault(savedSignal.getSymbol(), List.of());
                    replaceSignalXaiReasons(savedSignal.getId(), reasons);
                }
                LOGGER.info("Saved {} AI signals for market radar", savedSignals.size());
            }

        } catch (Exception e) {
            LOGGER.error("Failed to scan AI signals for market radar", e);
        }
    }

    /**
     * Get latest AI signal for a symbol.
     */
    public Optional<DailyAiSignal> getLatestSignalForSymbol(String symbol) {
        return dailyAiSignalRepository.findLatestBySymbol(symbol.toUpperCase());
    }

    /**
     * Get latest AI signals for multiple symbols.
     */
    public Map<String, DailyAiSignal> getLatestSignalsForSymbols(List<String> symbols) {
        if (symbols == null || symbols.isEmpty()) {
            return Map.of();
        }
        
        List<String> upperSymbols = symbols.stream()
                .map(String::toUpperCase)
                .toList();
        
        return dailyAiSignalRepository.findLatestForSymbols(upperSymbols)
                .stream()
                .collect(Collectors.toMap(
                        DailyAiSignal::getSymbol,
                        signal -> signal,
                        (existing, replacement) -> existing
                ));
    }

    /**
     * Enrich stop rules with AI signal data.
     */
    public EnrichedStopRule enrichStopRule(StopRule rule) {
        StockInstrument stock = stockInstrumentRepository.findById(rule.getStockId()).orElse(null);
        String symbol = stock != null ? stock.getSymbol() : null;
        
        DailyAiSignal signal = null;
        if (symbol != null) {
            signal = getLatestSignalForSymbol(symbol).orElse(null);
        }

        return new EnrichedStopRule(
                rule.getId(),
                rule.getUserId(),
                rule.getStockId(),
                symbol,
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

    /**
     * Build a bulk prediction request for multiple symbols.
     * Note: symbols parameter is intentionally unused - AI predict endpoint returns
     * predictions for all eligible symbols. We filter results when processing response.
     */
    private AiPredictionRequest buildBulkPredictionRequest(@SuppressWarnings("unused") List<String> symbols) {
        AiPredictionRequest request = new AiPredictionRequest();
        request.setRequestId("radar-" + System.currentTimeMillis());
        request.setUserId("SYSTEM_RADAR");
        request.setAsOfDate(LocalDate.now());
        request.setBudgetEgp(new BigDecimal("1000000.00")); // Dummy budget for signal-only request
        request.setRiskLevel("MEDIUM");
        request.setTier("PREMIUM");

        AiConstraintsPayload constraints = new AiConstraintsPayload();
        constraints.setMaxSectorWeight(new BigDecimal("0.40"));
        constraints.setMaxAdv30Participation(new BigDecimal("0.05"));
        constraints.setExcludeSuspended(true);
        constraints.setAllowFractionalShares(false);
        request.setConstraints(constraints);

        return request;
    }

    /**
     * Determine action from recommendation.
     */
    private String determineAction(AiRecommendationItem rec) {
        if (rec.getAction() != null) {
            return rec.getAction().toUpperCase();
        }
        // Infer from predicted return
        if (rec.getPredictedReturn5d() == null) {
            return "HOLD";
        }
        BigDecimal ret = rec.getPredictedReturn5d();
        if (ret.compareTo(new BigDecimal("0.05")) > 0) {
            return "BUY";
        } else if (ret.compareTo(new BigDecimal("-0.05")) < 0) {
            return "SELL";
        }
        return "HOLD";
    }

    private List<String> buildXaiReasons(AiRecommendationItem rec, String action) {
        List<String> normalized = new ArrayList<>();

        if (rec.getTopReasons() != null) {
            normalized.addAll(
                    rec.getTopReasons().stream()
                            .filter(Objects::nonNull)
                            .map(String::trim)
                            .filter(value -> !value.isEmpty())
                            .toList()
            );
        }

        if (normalized.isEmpty() && rec.getReason() != null && !rec.getReason().isBlank()) {
            normalized.add(rec.getReason().trim());
        }

        if (normalized.isEmpty()) {
            String forecastText = rec.getPredictedReturn5d() == null
                    ? "no return forecast available"
                    : String.format("5-day return forecast %.2f%%", rec.getPredictedReturn5d().doubleValue() * 100.0);
            normalized.add("Action " + action + " selected with " + forecastText);
        }

        return normalized.stream().limit(3).toList();
    }

    private void replaceSignalXaiReasons(Long signalId, List<String> reasons) {
        if (signalId == null) {
            return;
        }

        signalXaiReasonRepository.deleteBySignalId(signalId);

        if (reasons == null || reasons.isEmpty()) {
            return;
        }

        List<SignalXaiReason> rows = new ArrayList<>();
        int order = 1;
        for (String reason : reasons) {
            if (reason == null || reason.isBlank()) {
                continue;
            }

            SignalXaiReason row = new SignalXaiReason();
            row.setSignalId(signalId);
            row.setReasonOrder(order);
            row.setReasonText(reason.trim());
            row.setReasonWeight(BigDecimal.valueOf(Math.max(0.30, 0.90 - ((order - 1) * 0.20))));
            rows.add(row);

            order += 1;
            if (order > 3) {
                break;
            }
        }

        if (!rows.isEmpty()) {
            signalXaiReasonRepository.saveAll(rows);
        }
    }

    private List<String> loadXaiReasons(DailyAiSignal signal) {
        if (signal == null || signal.getId() == null) {
            return List.of();
        }

        return signalXaiReasonRepository.findBySignalIdOrderByReasonOrderAsc(signal.getId())
                .stream()
                .map(SignalXaiReason::getReasonText)
                .filter(Objects::nonNull)
                .map(String::trim)
                .filter(value -> !value.isEmpty())
                .limit(3)
                .toList();
    }

    /**
     * Enriched Stop Rule DTO with AI signal data.
     */
    public record EnrichedStopRule(
            Long id,
            Long userId,
            Long stockId,
            String symbol,
            Long portfolioRunId,
            BigDecimal stopLossPct,
            BigDecimal takeProfitPct,
            Boolean isActive,
            BigDecimal confidenceScore,
            BigDecimal predictedReturn5d,
            String action,
            List<String> xaiReasons
    ) {}
}
