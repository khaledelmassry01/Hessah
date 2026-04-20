package com.egx.core.service;

import com.egx.core.domain.ModelPerformanceLog;
import com.egx.core.repository.ModelPerformanceLogRepository;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
public class ModelPerformanceService {

    private static final String DEFAULT_MODEL_VERSION = "mpt-egx30-v4-learning";
    private static final int MIN_SUMMARY_LIMIT = 10;
    private static final int MAX_SUMMARY_LIMIT = 20;
    private static final int DEFAULT_SUMMARY_LIMIT = 15;
    private static final BigDecimal MIN_ACCURACY_DENOMINATOR = new BigDecimal("0.00010000");

    private final ModelPerformanceLogRepository modelPerformanceLogRepository;

    public ModelPerformanceService(ModelPerformanceLogRepository modelPerformanceLogRepository) {
        this.modelPerformanceLogRepository = modelPerformanceLogRepository;
    }

    @Transactional
    public LogResult logPerformance(LogCommand command) {
        String riskLevel = normalizeRiskLevel(command.riskLevel());
        AdaptiveParameterResult defaults = defaultParameters(riskLevel);

        ModelPerformanceLog log = new ModelPerformanceLog();
        log.setRequestId(normalizeLength(command.requestId(), 64));
        log.setUserId(command.userId());
        log.setRiskLevel(riskLevel);
        log.setModelVersion(resolveModelVersion(command.modelVersion()));

        LocalDate historicalDate = command.historicalDate() == null ? LocalDate.now() : command.historicalDate();
        LocalDate evaluationDate = command.evaluationDate() == null ? historicalDate : command.evaluationDate();

        log.setHistoricalDate(historicalDate);
        log.setEvaluationDate(evaluationDate);
        log.setHorizonDays(command.horizonDays() == null ? 0 : Math.max(0, command.horizonDays()));

        log.setBudgetEgp(scale(command.budgetEgp(), 4, BigDecimal.ZERO));
        log.setPredictedReturn(scale(command.predictedReturn(), 8, BigDecimal.ZERO));
        log.setActualReturn(scale(command.actualReturn(), 8, BigDecimal.ZERO));
        log.setPredictionError(scale(command.predictionError(), 8, BigDecimal.ZERO));

        log.setRiskFreeRate(scale(command.riskFreeRate(), 6, defaults.riskFreeRate()));
        log.setCovarianceShrinkage(scale(command.covarianceShrinkage(), 6, defaults.covarianceShrinkage()));
        log.setRunStatus(resolveRunStatus(command.runStatus()));
        log.setCreatedAt(LocalDateTime.now());

        ModelPerformanceLog saved = modelPerformanceLogRepository.save(log);
        return new LogResult(saved.getId(), riskLevel);
    }

    @Transactional(readOnly = true)
    public AdaptiveParameterResult resolveAdaptiveParameters(String riskLevel) {
        String normalizedRiskLevel = normalizeRiskLevel(riskLevel);
        AdaptiveParameterResult defaults = defaultParameters(normalizedRiskLevel);

        List<ModelPerformanceLog> logs = modelPerformanceLogRepository
                .findTop200ByRiskLevelOrderByCreatedAtDesc(normalizedRiskLevel);

        if (logs.isEmpty()) {
            return new AdaptiveParameterResult(
                    normalizedRiskLevel,
                    defaults.riskFreeRate(),
                    defaults.covarianceShrinkage(),
                    0,
                    "default"
            );
        }

        Map<ParameterKey, ErrorStats> statsByParameter = new HashMap<>();

        for (ModelPerformanceLog log : logs) {
            BigDecimal riskFree = scale(log.getRiskFreeRate(), 6, defaults.riskFreeRate());
            BigDecimal covarianceShrinkage = scale(log.getCovarianceShrinkage(), 6, defaults.covarianceShrinkage());
            BigDecimal absoluteError = scale(log.getPredictionError(), 8, BigDecimal.ZERO).abs();

            ParameterKey key = new ParameterKey(riskFree, covarianceShrinkage);
            ErrorStats stats = statsByParameter.computeIfAbsent(key, ignored -> new ErrorStats());
            stats.totalAbsoluteError = stats.totalAbsoluteError.add(absoluteError);
            stats.count = stats.count + 1;
        }

        ParameterKey bestKey = null;
        BigDecimal bestMae = null;
        int bestCount = 0;

        for (Map.Entry<ParameterKey, ErrorStats> entry : statsByParameter.entrySet()) {
            ErrorStats stats = entry.getValue();
            if (stats.count < 3) {
                continue;
            }

            BigDecimal mae = stats.totalAbsoluteError
                    .divide(BigDecimal.valueOf(stats.count), 8, RoundingMode.HALF_DOWN);

            if (bestKey == null
                    || mae.compareTo(bestMae) < 0
                    || (mae.compareTo(bestMae) == 0 && stats.count > bestCount)) {
                bestKey = entry.getKey();
                bestMae = mae;
                bestCount = stats.count;
            }
        }

        if (bestKey == null) {
            return new AdaptiveParameterResult(
                    normalizedRiskLevel,
                    defaults.riskFreeRate(),
                    defaults.covarianceShrinkage(),
                    logs.size(),
                    "default-insufficient-history"
            );
        }

        return new AdaptiveParameterResult(
                normalizedRiskLevel,
                bestKey.riskFreeRate(),
                bestKey.covarianceShrinkage(),
                logs.size(),
                "historical-performance"
        );
    }

    @Transactional(readOnly = true)
    public List<PerformanceSummaryEntry> fetchPerformanceSummary(Integer requestedLimit) {
        int limit = sanitizeSummaryLimit(requestedLimit);

        return modelPerformanceLogRepository
                .findByOrderByCreatedAtDesc(PageRequest.of(0, limit))
                .stream()
                .map(this::toSummaryEntry)
                .toList();
    }

    private AdaptiveParameterResult defaultParameters(String riskLevel) {
        return switch (riskLevel) {
            case "LOW" -> new AdaptiveParameterResult("LOW", new BigDecimal("0.180000"), new BigDecimal("0.250000"), 0, "default");
            case "HIGH" -> new AdaptiveParameterResult("HIGH", new BigDecimal("0.280000"), new BigDecimal("0.050000"), 0, "default");
            default -> new AdaptiveParameterResult("MEDIUM", new BigDecimal("0.230000"), new BigDecimal("0.120000"), 0, "default");
        };
    }

    private String normalizeRiskLevel(String riskLevel) {
        if (riskLevel == null || riskLevel.isBlank()) {
            return "MEDIUM";
        }

        String normalized = riskLevel.trim().toUpperCase();
        if ("LOW".equals(normalized) || "MEDIUM".equals(normalized) || "HIGH".equals(normalized)) {
            return normalized;
        }

        return "MEDIUM";
    }

    private String resolveModelVersion(String modelVersion) {
        if (modelVersion == null || modelVersion.isBlank()) {
            return DEFAULT_MODEL_VERSION;
        }
        return normalizeLength(modelVersion.trim(), 64);
    }

    private String resolveRunStatus(String runStatus) {
        if (runStatus == null || runStatus.isBlank()) {
            return "UNKNOWN";
        }
        return normalizeLength(runStatus.trim().toUpperCase(), 16);
    }

    private String normalizeLength(String value, int maxLength) {
        if (value == null) {
            return null;
        }

        if (value.length() <= maxLength) {
            return value;
        }

        return value.substring(0, maxLength);
    }

    private BigDecimal scale(BigDecimal value, int scale, BigDecimal fallback) {
        if (value == null) {
            return fallback.setScale(scale, RoundingMode.HALF_DOWN);
        }
        return value.setScale(scale, RoundingMode.HALF_DOWN);
    }

    private int sanitizeSummaryLimit(Integer requestedLimit) {
        if (requestedLimit == null) {
            return DEFAULT_SUMMARY_LIMIT;
        }

        return Math.max(MIN_SUMMARY_LIMIT, Math.min(MAX_SUMMARY_LIMIT, requestedLimit));
    }

    private PerformanceSummaryEntry toSummaryEntry(ModelPerformanceLog log) {
        BigDecimal predictedReturn = scale(log.getPredictedReturn(), 8, BigDecimal.ZERO);
        BigDecimal actualReturn = scale(log.getActualReturn(), 8, BigDecimal.ZERO);

        BigDecimal fallbackError = predictedReturn.subtract(actualReturn).abs();
        BigDecimal absoluteError = scale(log.getPredictionError(), 8, fallbackError).abs();
        BigDecimal denominator = actualReturn.abs().max(MIN_ACCURACY_DENOMINATOR);
        BigDecimal normalizedError = absoluteError.divide(denominator, 8, RoundingMode.HALF_DOWN);

        BigDecimal accuracyScore = BigDecimal.ONE.subtract(normalizedError);
        if (accuracyScore.compareTo(BigDecimal.ZERO) < 0) {
            accuracyScore = BigDecimal.ZERO;
        }
        if (accuracyScore.compareTo(BigDecimal.ONE) > 0) {
            accuracyScore = BigDecimal.ONE;
        }

        LocalDate testDate = log.getEvaluationDate() != null
                ? log.getEvaluationDate()
                : (log.getHistoricalDate() != null ? log.getHistoricalDate() : LocalDate.now());

        return new PerformanceSummaryEntry(
                testDate,
                predictedReturn,
                actualReturn,
                accuracyScore.setScale(4, RoundingMode.HALF_DOWN),
                Map.of(
                        "riskFreeRate", scale(log.getRiskFreeRate(), 6, BigDecimal.ZERO),
                        "covarianceShrinkage", scale(log.getCovarianceShrinkage(), 6, BigDecimal.ZERO)
                )
        );
    }

    public record LogCommand(
            String requestId,
            Long userId,
            String riskLevel,
            String modelVersion,
            LocalDate historicalDate,
            LocalDate evaluationDate,
            Integer horizonDays,
            BigDecimal budgetEgp,
            BigDecimal predictedReturn,
            BigDecimal actualReturn,
            BigDecimal predictionError,
            BigDecimal riskFreeRate,
            BigDecimal covarianceShrinkage,
            String runStatus
    ) {
    }

    public record LogResult(Long logId, String riskLevel) {
    }

    public record AdaptiveParameterResult(
            String riskLevel,
            BigDecimal riskFreeRate,
            BigDecimal covarianceShrinkage,
            int sampleSize,
            String source
    ) {
    }

        public record PerformanceSummaryEntry(
            LocalDate testDate,
            BigDecimal predictedReturn,
            BigDecimal actualReturn,
            BigDecimal accuracyScore,
            Map<String, BigDecimal> optimizedParameters
        ) {
        }

    private record ParameterKey(BigDecimal riskFreeRate, BigDecimal covarianceShrinkage) {
    }

    private static class ErrorStats {
        private BigDecimal totalAbsoluteError = BigDecimal.ZERO;
        private int count = 0;
    }
}
