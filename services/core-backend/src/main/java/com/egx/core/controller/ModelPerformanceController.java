package com.egx.core.controller;

import com.egx.core.service.ModelPerformanceService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.time.LocalDate;

@RestController
@RequestMapping({"/model-performance", "/api/core/model-performance"})
public class ModelPerformanceController {

    private final ModelPerformanceService modelPerformanceService;

    public ModelPerformanceController(ModelPerformanceService modelPerformanceService) {
        this.modelPerformanceService = modelPerformanceService;
    }

    @PostMapping("/log")
    public LogResponse logPerformance(@RequestBody PerformanceLogRequest request) {
        ModelPerformanceService.LogResult result = modelPerformanceService.logPerformance(
                new ModelPerformanceService.LogCommand(
                        request.requestId(),
                        request.userId(),
                        request.riskLevel(),
                        request.modelVersion(),
                        request.historicalDate(),
                        request.evaluationDate(),
                        request.horizonDays(),
                        request.budgetEgp(),
                        request.predictedReturn(),
                        request.actualReturn(),
                        request.predictionError(),
                        request.riskFreeRate(),
                        request.covarianceShrinkage(),
                        request.runStatus()
                )
        );

        return new LogResponse("SUCCESS", result.logId(), result.riskLevel());
    }

    @GetMapping("/params")
    public AdaptiveParameterResponse resolveAdaptiveParameters(
            @RequestParam(name = "riskLevel", required = false) String riskLevel
    ) {
        ModelPerformanceService.AdaptiveParameterResult result = modelPerformanceService
                .resolveAdaptiveParameters(riskLevel);

        return new AdaptiveParameterResponse(
                result.riskLevel(),
                result.riskFreeRate(),
                result.covarianceShrinkage(),
                result.sampleSize(),
                result.source()
        );
    }

    public record PerformanceLogRequest(
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

    public record LogResponse(String status, Long logId, String riskLevel) {
    }

    public record AdaptiveParameterResponse(
            String riskLevel,
            BigDecimal riskFreeRate,
            BigDecimal covarianceShrinkage,
            int sampleSize,
            String source
    ) {
    }
}
