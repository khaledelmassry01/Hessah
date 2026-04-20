package com.egx.core.controller;

import java.util.List;

import org.springframework.http.HttpStatus;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

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

    public StopRuleController(PremiumAccessService premiumAccessService, StopRuleRepository stopRuleRepository) {
        this.premiumAccessService = premiumAccessService;
        this.stopRuleRepository = stopRuleRepository;
    }

    @GetMapping
    public List<PremiumController.StopRuleResponse> listStopRules(Authentication authentication) {
        Long userId = resolveUserId(authentication);
        premiumAccessService.assertPremium(userId);

        return stopRuleRepository.findByUserIdOrderByUpdatedAtDesc(userId)
                .stream()
                .map(rule -> new PremiumController.StopRuleResponse(
                        rule.getId(),
                        rule.getUserId(),
                        rule.getStockId(),
                        rule.getPortfolioRunId(),
                        rule.getStopLossPct(),
                        rule.getTakeProfitPct(),
                        rule.getIsActive()
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
}