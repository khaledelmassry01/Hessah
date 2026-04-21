package com.egx.core.service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import org.springframework.stereotype.Service;

import com.egx.core.client.dto.AiAllocationItem;

@Service
public class PortfolioOptimizer {

    private static final BigDecimal ZERO = BigDecimal.ZERO;
    private static final BigDecimal ONE = BigDecimal.ONE;
    private static final int SCALE = 8;

    public OptimizationResult optimize(
            List<AiAllocationItem> rawAllocations,
            BigDecimal maxSectorWeight,
            BigDecimal minConfidenceThreshold
    ) {
        if (rawAllocations == null || rawAllocations.isEmpty()) {
            return new OptimizationResult(List.of(), ONE, List.of("PortfolioOptimizer received no allocations; moved to CASH"));
        }

        BigDecimal sectorCap = clamp(maxSectorWeight, ZERO, ONE);
        BigDecimal confidenceFloor = clamp(minConfidenceThreshold, ZERO, ONE);

        List<Candidate> candidates = normalizeCandidates(rawAllocations);
        if (candidates.isEmpty()) {
            return new OptimizationResult(List.of(), ONE, List.of("PortfolioOptimizer found no positive weights; moved to CASH"));
        }

        Map<String, BigDecimal> scoreBySymbol = new LinkedHashMap<>();
        Map<String, String> sectorBySymbol = new LinkedHashMap<>();

        BigDecimal cashWeight = ZERO;
        int belowThresholdCount = 0;

        for (Candidate candidate : candidates) {
            if (candidate.confidence().compareTo(confidenceFloor) < 0) {
                cashWeight = cashWeight.add(candidate.normalizedWeight());
                belowThresholdCount += 1;
                continue;
            }

            BigDecimal positiveExpected = candidate.predictedReturn().max(ZERO);
            BigDecimal score = positiveExpected.multiply(candidate.confidence());
            if (score.compareTo(ZERO) <= 0) {
                score = candidate.normalizedWeight().multiply(candidate.confidence());
            }

            if (score.compareTo(ZERO) <= 0) {
                cashWeight = cashWeight.add(candidate.normalizedWeight());
                continue;
            }

            scoreBySymbol.put(candidate.symbol(), score);
            sectorBySymbol.put(candidate.symbol(), candidate.sector());
        }

        List<String> warnings = new ArrayList<>();
        if (belowThresholdCount > 0) {
            warnings.add(
                    "PortfolioOptimizer moved " + belowThresholdCount
                            + " low-confidence symbol(s) below threshold "
                            + confidenceFloor.setScale(2, RoundingMode.HALF_DOWN)
                            + " to CASH"
            );
        }

        BigDecimal investableWeight = ONE.subtract(cashWeight).max(ZERO);
        if (scoreBySymbol.isEmpty() || investableWeight.compareTo(ZERO) <= 0) {
            warnings.add("No symbols satisfied confidence/return criteria; 100% CASH allocation");
            return new OptimizationResult(List.of(), ONE, warnings);
        }

        BigDecimal scoreTotal = scoreBySymbol.values().stream()
                .reduce(ZERO, BigDecimal::add);

        if (scoreTotal.compareTo(ZERO) <= 0) {
            warnings.add("Optimization scores resolved to zero; 100% CASH allocation");
            return new OptimizationResult(List.of(), ONE, warnings);
        }

        Map<String, BigDecimal> provisionalWeights = new LinkedHashMap<>();
        for (Map.Entry<String, BigDecimal> entry : scoreBySymbol.entrySet()) {
            BigDecimal proportional = entry.getValue().divide(scoreTotal, SCALE + 6, RoundingMode.HALF_DOWN);
            provisionalWeights.put(entry.getKey(), proportional.multiply(investableWeight));
        }

        Map<String, BigDecimal> sectorUsage = new LinkedHashMap<>();
        Map<String, BigDecimal> acceptedWeights = new LinkedHashMap<>();

        for (Map.Entry<String, BigDecimal> entry : provisionalWeights.entrySet()) {
            String symbol = entry.getKey();
            BigDecimal requestedWeight = entry.getValue();
            String sector = sectorBySymbol.getOrDefault(symbol, "UNMAPPED");

            BigDecimal used = sectorUsage.getOrDefault(sector, ZERO);
            BigDecimal room = sectorCap.subtract(used).max(ZERO);
            BigDecimal accepted = requestedWeight.min(room).max(ZERO);
            BigDecimal overflow = requestedWeight.subtract(accepted).max(ZERO);

            if (accepted.compareTo(ZERO) > 0) {
                acceptedWeights.put(symbol, accepted);
                sectorUsage.put(sector, used.add(accepted));
            }
            if (overflow.compareTo(ZERO) > 0) {
                cashWeight = cashWeight.add(overflow);
            }
        }

        BigDecimal allocated = acceptedWeights.values().stream().reduce(ZERO, BigDecimal::add);
        BigDecimal residual = ONE.subtract(allocated).max(ZERO);
        cashWeight = cashWeight.max(residual).min(ONE);

        List<AiAllocationItem> optimized = new ArrayList<>();
        for (Candidate candidate : candidates) {
            BigDecimal finalWeight = acceptedWeights.getOrDefault(candidate.symbol(), ZERO);
            if (finalWeight.compareTo(ZERO) <= 0) {
                continue;
            }

            AiAllocationItem item = new AiAllocationItem();
            item.setSymbol(candidate.symbol());
            item.setSector(candidate.sector());
            item.setWeight(finalWeight.setScale(SCALE, RoundingMode.HALF_DOWN));
            item.setPredictedReturn5d(candidate.predictedReturn());
            item.setConfidenceScore(candidate.confidence());
            optimized.add(item);
        }

        optimized.sort((left, right) -> right.getWeight().compareTo(left.getWeight()));
        if (cashWeight.compareTo(ZERO) > 0) {
            warnings.add(
                    "PortfolioOptimizer allocated "
                            + cashWeight.setScale(4, RoundingMode.HALF_DOWN)
                            + " to CASH after cap/threshold controls"
            );
        }

        return new OptimizationResult(
                optimized,
                cashWeight.setScale(SCALE, RoundingMode.HALF_DOWN),
                warnings
        );
    }

    private List<Candidate> normalizeCandidates(List<AiAllocationItem> allocations) {
        List<AiAllocationItem> positive = allocations.stream()
                .filter(item -> item != null && item.getWeight() != null && item.getWeight().compareTo(ZERO) > 0)
                .toList();

        if (positive.isEmpty()) {
            return List.of();
        }

        BigDecimal totalWeight = positive.stream()
                .map(AiAllocationItem::getWeight)
                .reduce(ZERO, BigDecimal::add);

        if (totalWeight.compareTo(ZERO) <= 0) {
            return List.of();
        }

        List<Candidate> normalized = new ArrayList<>();
        for (AiAllocationItem item : positive) {
            String symbol = sanitizeSymbol(item.getSymbol());
            if (symbol == null) {
                continue;
            }

            String sector = sanitizeSector(item.getSector());
            BigDecimal normalizedWeight = item.getWeight().divide(totalWeight, SCALE + 6, RoundingMode.HALF_DOWN);
            BigDecimal predictedReturn = item.getPredictedReturn5d() == null ? ZERO : item.getPredictedReturn5d();
            BigDecimal confidence = clamp(item.getConfidenceScore(), ZERO, ONE);
            if (confidence.compareTo(ZERO) <= 0) {
                confidence = ONE;
            }

            normalized.add(new Candidate(symbol, sector, normalizedWeight, predictedReturn, confidence));
        }

        return normalized;
    }

    private BigDecimal clamp(BigDecimal value, BigDecimal minimum, BigDecimal maximum) {
        if (value == null) {
            return minimum;
        }
        if (value.compareTo(minimum) < 0) {
            return minimum;
        }
        if (value.compareTo(maximum) > 0) {
            return maximum;
        }
        return value;
    }

    private String sanitizeSymbol(String symbol) {
        if (symbol == null || symbol.isBlank()) {
            return null;
        }
        return symbol.trim().toUpperCase(Locale.ROOT);
    }

    private String sanitizeSector(String sector) {
        if (sector == null || sector.isBlank()) {
            return "UNMAPPED";
        }
        return sector.trim().toUpperCase(Locale.ROOT);
    }

    private record Candidate(
            String symbol,
            String sector,
            BigDecimal normalizedWeight,
            BigDecimal predictedReturn,
            BigDecimal confidence
    ) {
    }

    public record OptimizationResult(
            List<AiAllocationItem> allocations,
            BigDecimal cashWeight,
            List<String> warnings
    ) {
    }
}
