package com.egx.core.service;

import com.egx.core.domain.MarketDailyBar;
import com.egx.core.domain.PositionLot;
import com.egx.core.domain.StopAlert;
import com.egx.core.domain.StopRule;
import com.egx.core.domain.enums.StopAlertStatus;
import com.egx.core.domain.enums.StopTriggerType;
import com.egx.core.repository.MarketDailyBarRepository;
import com.egx.core.repository.PositionLotRepository;
import com.egx.core.repository.StopAlertRepository;
import com.egx.core.repository.StopRuleRepository;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.List;
import java.util.Optional;

@Service
public class MarketMonitorService {

    private final StopRuleRepository stopRuleRepository;
    private final StopAlertRepository stopAlertRepository;
    private final PositionLotRepository positionLotRepository;
    private final MarketDailyBarRepository marketDailyBarRepository;
    private final PremiumAccessService premiumAccessService;

    public MarketMonitorService(
            StopRuleRepository stopRuleRepository,
            StopAlertRepository stopAlertRepository,
            PositionLotRepository positionLotRepository,
            MarketDailyBarRepository marketDailyBarRepository,
            PremiumAccessService premiumAccessService
    ) {
        this.stopRuleRepository = stopRuleRepository;
        this.stopAlertRepository = stopAlertRepository;
        this.positionLotRepository = positionLotRepository;
        this.marketDailyBarRepository = marketDailyBarRepository;
        this.premiumAccessService = premiumAccessService;
    }

    @Scheduled(cron = "${market.monitor.cron:0 0 15 * * *}")
    @Transactional
    public void monitorPremiumStops() {
        List<StopRule> activeRules = stopRuleRepository.findByIsActiveTrue();
        if (activeRules.isEmpty()) {
            return;
        }

        LocalDateTime now = LocalDateTime.now();
        LocalDateTime dayStart = now.toLocalDate().atStartOfDay();
        LocalDateTime dayEnd = now.toLocalDate().atTime(LocalTime.MAX);

        for (StopRule rule : activeRules) {
            if (!premiumAccessService.isPremium(rule.getUserId())) {
                continue;
            }

            Optional<BigDecimal> acquisitionCostOpt = weightedAcquisitionCost(rule.getUserId(), rule.getStockId());
            Optional<BigDecimal> marketPriceOpt = latestMarketPrice(rule.getStockId());
            if (acquisitionCostOpt.isEmpty() || marketPriceOpt.isEmpty()) {
                continue;
            }

            BigDecimal acquisitionCost = acquisitionCostOpt.get();
            BigDecimal marketPrice = marketPriceOpt.get();

            BigDecimal stopLossTrigger = acquisitionCost.multiply(BigDecimal.ONE.subtract(normalizePct(rule.getStopLossPct())));
            BigDecimal takeProfitTrigger = acquisitionCost.multiply(BigDecimal.ONE.add(normalizePct(rule.getTakeProfitPct())));

            if (marketPrice.compareTo(stopLossTrigger) <= 0) {
                createTriggeredAlertIfMissing(
                        rule,
                        StopTriggerType.STOP_LOSS,
                        stopLossTrigger,
                        marketPrice,
                        dayStart,
                        dayEnd
                );
            }

            if (marketPrice.compareTo(takeProfitTrigger) >= 0) {
                createTriggeredAlertIfMissing(
                        rule,
                        StopTriggerType.TAKE_PROFIT,
                        takeProfitTrigger,
                        marketPrice,
                        dayStart,
                        dayEnd
                );
            }
        }
    }

    private Optional<BigDecimal> weightedAcquisitionCost(Long userId, Long stockId) {
        List<PositionLot> lots = positionLotRepository.findByUserIdAndStockId(userId, stockId);
        if (lots.isEmpty()) {
            return Optional.empty();
        }

        BigDecimal totalCost = BigDecimal.ZERO;
        long totalQuantity = 0L;

        for (PositionLot lot : lots) {
            if (lot.getQuantityAvailable() == null || lot.getQuantityAvailable() <= 0 || lot.getAvgCost() == null) {
                continue;
            }

            totalQuantity += lot.getQuantityAvailable();
            totalCost = totalCost.add(
                    lot.getAvgCost().multiply(BigDecimal.valueOf(lot.getQuantityAvailable()))
            );
        }

        if (totalQuantity <= 0) {
            return Optional.empty();
        }

        return Optional.of(totalCost.divide(BigDecimal.valueOf(totalQuantity), 6, RoundingMode.HALF_DOWN));
    }

    private Optional<BigDecimal> latestMarketPrice(Long stockId) {
        return marketDailyBarRepository
                .findTopByStockIdOrderByTradeDateDesc(stockId)
                .map(MarketDailyBar::getClosePrice);
    }

    private void createTriggeredAlertIfMissing(
            StopRule rule,
            StopTriggerType triggerType,
            BigDecimal triggerPrice,
            BigDecimal marketPrice,
            LocalDateTime dayStart,
            LocalDateTime dayEnd
    ) {
        boolean existsToday = stopAlertRepository.existsByStopRuleIdAndTriggerTypeAndTriggeredAtBetween(
                rule.getId(),
                triggerType,
                dayStart,
                dayEnd
        );

        if (existsToday) {
            return;
        }

        StopAlert alert = new StopAlert();
        alert.setStopRuleId(rule.getId());
        alert.setTriggerType(triggerType);
        alert.setTriggerPrice(triggerPrice.setScale(4, RoundingMode.HALF_DOWN));
        alert.setMarketPrice(marketPrice.setScale(4, RoundingMode.HALF_DOWN));
        alert.setTriggeredAt(LocalDateTime.now());
        alert.setAlertStatus(StopAlertStatus.TRIGGERED);
        stopAlertRepository.save(alert);
    }

    private BigDecimal normalizePct(BigDecimal pct) {
        if (pct == null || pct.compareTo(BigDecimal.ZERO) <= 0) {
            return BigDecimal.ZERO;
        }
        if (pct.compareTo(BigDecimal.ONE) > 0) {
            return pct.divide(BigDecimal.valueOf(100), 6, RoundingMode.HALF_DOWN);
        }
        return pct;
    }
}
