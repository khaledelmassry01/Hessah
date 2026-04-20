package com.egx.core.domain;

import com.egx.core.domain.enums.StopAlertStatus;
import com.egx.core.domain.enums.StopTriggerType;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Entity
@Table(name = "stop_alerts")
public class StopAlert {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "stop_rule_id", nullable = false)
    private Long stopRuleId;

    @Enumerated(EnumType.STRING)
    @Column(name = "trigger_type", nullable = false, length = 16)
    private StopTriggerType triggerType;

    @Column(name = "trigger_price", nullable = false, precision = 19, scale = 4)
    private BigDecimal triggerPrice;

    @Column(name = "market_price", nullable = false, precision = 19, scale = 4)
    private BigDecimal marketPrice;

    @Column(name = "triggered_at", nullable = false)
    private LocalDateTime triggeredAt;

    @Enumerated(EnumType.STRING)
    @Column(name = "alert_status", nullable = false, length = 16)
    private StopAlertStatus alertStatus;

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public Long getStopRuleId() {
        return stopRuleId;
    }

    public void setStopRuleId(Long stopRuleId) {
        this.stopRuleId = stopRuleId;
    }

    public StopTriggerType getTriggerType() {
        return triggerType;
    }

    public void setTriggerType(StopTriggerType triggerType) {
        this.triggerType = triggerType;
    }

    public BigDecimal getTriggerPrice() {
        return triggerPrice;
    }

    public void setTriggerPrice(BigDecimal triggerPrice) {
        this.triggerPrice = triggerPrice;
    }

    public BigDecimal getMarketPrice() {
        return marketPrice;
    }

    public void setMarketPrice(BigDecimal marketPrice) {
        this.marketPrice = marketPrice;
    }

    public LocalDateTime getTriggeredAt() {
        return triggeredAt;
    }

    public void setTriggeredAt(LocalDateTime triggeredAt) {
        this.triggeredAt = triggeredAt;
    }

    public StopAlertStatus getAlertStatus() {
        return alertStatus;
    }

    public void setAlertStatus(StopAlertStatus alertStatus) {
        this.alertStatus = alertStatus;
    }

}