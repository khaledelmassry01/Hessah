package com.egx.core.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Entity
@Table(name = "stop_rules")
public class StopRule {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "stock_id", nullable = false)
    private Long stockId;

    @Column(name = "portfolio_run_id")
    private Long portfolioRunId;

    @Column(name = "stop_loss_pct", nullable = false, precision = 6, scale = 3)
    private BigDecimal stopLossPct;

    @Column(name = "take_profit_pct", nullable = false, precision = 6, scale = 3)
    private BigDecimal takeProfitPct;

    @Column(name = "is_active", nullable = false)
    private Boolean isActive;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt;

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public Long getUserId() {
        return userId;
    }

    public void setUserId(Long userId) {
        this.userId = userId;
    }

    public Long getStockId() {
        return stockId;
    }

    public void setStockId(Long stockId) {
        this.stockId = stockId;
    }

    public Long getPortfolioRunId() {
        return portfolioRunId;
    }

    public void setPortfolioRunId(Long portfolioRunId) {
        this.portfolioRunId = portfolioRunId;
    }

    public BigDecimal getStopLossPct() {
        return stopLossPct;
    }

    public void setStopLossPct(BigDecimal stopLossPct) {
        this.stopLossPct = stopLossPct;
    }

    public BigDecimal getTakeProfitPct() {
        return takeProfitPct;
    }

    public void setTakeProfitPct(BigDecimal takeProfitPct) {
        this.takeProfitPct = takeProfitPct;
    }

    public Boolean getIsActive() {
        return isActive;
    }

    public void setIsActive(Boolean isActive) {
        this.isActive = isActive;
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(LocalDateTime createdAt) {
        this.createdAt = createdAt;
    }

    public LocalDateTime getUpdatedAt() {
        return updatedAt;
    }

    public void setUpdatedAt(LocalDateTime updatedAt) {
        this.updatedAt = updatedAt;
    }

}