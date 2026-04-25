package com.egx.core.controller;

import java.util.List;

import org.springframework.http.HttpStatus;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import com.egx.core.domain.DailyAiSignal;
import com.egx.core.domain.StockInstrument;
import com.egx.core.repository.DailyAiSignalRepository;
import com.egx.core.repository.StockInstrumentRepository;
import com.egx.core.repository.StopRuleRepository;
import com.egx.core.service.PremiumAccessService;

@RestController
@RequestMapping({
    "/stop-rules",
    "/api/core/stop-rules",
    "/premium/stop-rules",
    "/api/core/premium/stop-rules"
})
public class StopRuleController {

    private final PremiumAccessService premiumAccessService;
    private final StopRuleRepository stopRuleRepository;
    private final StockInstrumentRepository stockInstrumentRepository;
    private final DailyAiSignalRepository dailyAiSignalRepository;

    public StopRuleController(
            PremiumAccessService premiumAccessService,
            StopRuleRepository stopRuleRepository,
            StockInstrumentRepository stockInstrumentRepository,
            DailyAiSignalRepository dailyAiSignalRepository
    ) {
        this.premiumAccessService = premiumAccessService;
        this.stopRuleRepository = stopRuleRepository;
        this.stockInstrumentRepository = stockInstrumentRepository;
        this.dailyAiSignalRepository = dailyAiSignalRepository;
    }

    @GetMapping
    public List<PremiumController.StopRuleResponse> listStopRules(Authentication authentication) {
        Long userId = resolveUserId(authentication);
        premiumAccessService.assertPremium(userId);

        return stopRuleRepository.findByUserIdOrderByUpdatedAtDesc(userId)
                .stream()
                .map(this::enrichStopRuleWithAiSignal)
                .toList();
    }

    private PremiumController.StopRuleResponse enrichStopRuleWithAiSignal(com.egx.core.domain.StopRule rule) {
        StockInstrument stock = stockInstrumentRepository.findById(rule.getStockId()).orElse(null);
        String symbol = stock != null ? stock.getSymbol() : null;

        DailyAiSignal signal = null;
        if (symbol != null) {
            signal = dailyAiSignalRepository.findLatestBySymbol(symbol).orElse(null);
        }

        return new PremiumController.StopRuleResponse(
                rule.getId(),
                rule.getUserId(),
                rule.getStockId(),
                symbol,
                rule.getPortfolioRunId(),
                rule.getStopLossPct(),
                rule.getTakeProfitPct(),
                rule.getIsActive(),
                signal != null ? signal.getConfidenceScore() : null,
                null, // predictedReturn5d removed (5NF compliance)
                signal != null ? signal.getAction() : "UNKNOWN",
                List.of() // xaiReasons removed (4NF compliance - now in signal_xai_reasons table)
        );
    }

    private List<String> parseXaiReasons(String reasons) {
        if (reasons == null || reasons.isBlank()) {
            return List.of();
        }
        return List.of(reasons.split("; "));
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
}