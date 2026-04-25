package com.egx.core.scheduler;

import com.egx.core.service.MarketRadarService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * Market Radar Scheduler - Daily AI Market Scanner.
 * Runs at 4:00 PM (16:00) Sunday-Thursday (after Egyptian market close).
 * Fetches AI predictions for all active stop rules and stores them
 * for the Market Watch dashboard.
 */
@Component
public class MarketRadarScheduler {

    private static final Logger LOGGER = LoggerFactory.getLogger(MarketRadarScheduler.class);

    private final MarketRadarService marketRadarService;

    public MarketRadarScheduler(MarketRadarService marketRadarService) {
        this.marketRadarService = marketRadarService;
    }

    /**
     * Daily AI Market Radar Scan.
     * Cron: 0 0 16 * * SUN-THU (4:00 PM, Sunday through Thursday)
     * Egyptian market closes at 2:30 PM, we run at 4:00 PM to allow
     * for any data ingestion delays.
     */
    @Scheduled(cron = "${market.radar.cron:0 0 16 * * SUN-THU}")
    public void dailyMarketRadarScan() {
        LOGGER.info("Starting daily AI market radar scan...");
        
        try {
            marketRadarService.scanAndSaveAiSignals();
            LOGGER.info("Daily AI market radar scan completed successfully");
        } catch (Exception e) {
            LOGGER.error("Daily AI market radar scan failed", e);
        }
    }

    /**
     * Manual trigger endpoint for testing/ad-hoc scans.
     */
    public void triggerManualScan() {
        LOGGER.info("Manual AI market radar scan triggered");
        dailyMarketRadarScan();
    }
}
