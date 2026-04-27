package com.egx.core.controller;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.egx.core.service.MarketRadarService;

/**
 * Admin Radar Controller - Manual triggers for Market Radar operations.
 * Provides endpoints for administrators to manually trigger AI scans
 * without waiting for the scheduled cron job.
 */
@RestController
@RequestMapping({"/admin", "/api/core/admin"})
public class AdminRadarController {

    private static final Logger LOGGER = LoggerFactory.getLogger(AdminRadarController.class);

    private final MarketRadarService marketRadarService;

    public AdminRadarController(MarketRadarService marketRadarService) {
        this.marketRadarService = marketRadarService;
    }

    /**
     * Admin health-check endpoint.
     * Returns a simple OK response to verify ADMIN role access is working.
     *
     * Requires ADMIN role.
     */
    @GetMapping("/health")
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<Map<String, Object>> adminHealthCheck() {
        return ResponseEntity.ok(Map.of(
                "status", "OK",
                "message", "Admin access verified",
                "timestamp", LocalDateTime.now().format(DateTimeFormatter.ISO_DATE_TIME)
        ));
    }

    /**
     * Manually trigger the Market Radar AI scan.
     * This endpoint allows administrators to populate the Market Watch
     * screen immediately without waiting for the 4 PM scheduled job.
     *
     * Requires ADMIN role.
     *
     * @return Success message with scan timestamp and symbol count
     */
    @PostMapping("/radar/trigger")
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<Map<String, Object>> triggerMarketRadarScan() {
        LOGGER.info("Manual market radar scan triggered by admin");

        try {
            // Get count of symbols that will be scanned
            var symbols = marketRadarService.getActiveStopRuleSymbols();
            int symbolCount = symbols.size();

            // Execute the scan
            marketRadarService.scanAndSaveAiSignals();

            LOGGER.info("Manual market radar scan completed for {} symbols", symbolCount);

            return ResponseEntity.ok(Map.of(
                    "status", "SUCCESS",
                    "message", "Market radar scan completed successfully",
                    "symbolsScanned", symbolCount,
                    "timestamp", LocalDateTime.now().format(DateTimeFormatter.ISO_DATE_TIME),
                    "nextScheduledRun", "16:00 today or next business day (SUN-THU)"
            ));

        } catch (Exception e) {
            LOGGER.error("Manual market radar scan failed", e);
            return ResponseEntity.internalServerError().body(Map.of(
                    "status", "ERROR",
                    "message", "Market radar scan failed: " + e.getMessage(),
                    "timestamp", LocalDateTime.now().format(DateTimeFormatter.ISO_DATE_TIME)
            ));
        }
    }

    /**
     * Get status of the market radar - counts of active symbols and latest signals.
     * Requires ADMIN role.
     */
    @PostMapping("/radar/status")
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<Map<String, Object>> getRadarStatus() {
        var symbols = marketRadarService.getActiveStopRuleSymbols();
        var latestSignals = marketRadarService.getLatestSignalsForSymbols(symbols);

        return ResponseEntity.ok(Map.of(
                "status", "OK",
                "activeStopRules", symbols.size(),
                "symbolsWithAiSignals", latestSignals.size(),
                "timestamp", LocalDateTime.now().format(DateTimeFormatter.ISO_DATE_TIME)
        ));
    }
}
