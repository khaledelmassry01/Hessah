package com.egx.core.controller;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import com.egx.core.service.ModelPerformanceService;

@RestController
@RequestMapping({"/ai", "/api/core/ai"})
public class AiPerformanceController {

    private final ModelPerformanceService modelPerformanceService;

    public AiPerformanceController(ModelPerformanceService modelPerformanceService) {
        this.modelPerformanceService = modelPerformanceService;
    }

    @GetMapping("/performance-summary")
    public List<PerformanceSummaryDto> getPerformanceSummary(
            Authentication authentication,
            @RequestParam(name = "limit", required = false) Integer limit
    ) {
        Long userId = resolveUserId(authentication);

        return modelPerformanceService.fetchPerformanceSummary(userId, limit)
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

    public record PerformanceSummaryDto(
            LocalDate testDate,
            BigDecimal predictedReturn,
            BigDecimal actualReturn,
            BigDecimal accuracyScore,
            Map<String, BigDecimal> optimizedParameters
    ) {
    }
}