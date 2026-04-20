package com.egx.core.controller;

import com.egx.core.service.ModelPerformanceService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping({"/ai", "/api/core/ai"})
public class AiPerformanceController {

    private final ModelPerformanceService modelPerformanceService;

    public AiPerformanceController(ModelPerformanceService modelPerformanceService) {
        this.modelPerformanceService = modelPerformanceService;
    }

    @GetMapping("/performance-summary")
    public List<PerformanceSummaryDto> getPerformanceSummary(
            @RequestParam(name = "limit", required = false) Integer limit
    ) {
        return modelPerformanceService.fetchPerformanceSummary(limit)
                .stream()
                .map(entry -> new PerformanceSummaryDto(
                        entry.testDate(),
                        entry.predictedReturn(),
                        entry.actualReturn(),
                        entry.accuracyScore(),
                        entry.optimizedParameters()
                ))
                .toList();
    }

    public record PerformanceSummaryDto(
            LocalDate testDate,
            BigDecimal predictedReturn,
            BigDecimal actualReturn,
            BigDecimal accuracyScore,
            Map<String, BigDecimal> optimizedParameters
    ) {
    }
}