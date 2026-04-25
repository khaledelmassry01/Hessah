package com.egx.core.domain;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

import com.egx.core.domain.enums.SettlementStatus;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "allocation_executions")
public class AllocationExecution {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "portfolio_run_id", nullable = false)
    private Long portfolioRunId;

    @Column(name = "stock_id", nullable = false)
    private Long stockId;

    @Column(name = "price_snapshot", nullable = false, precision = 19, scale = 4)
    private BigDecimal priceSnapshot;

    @Column(name = "target_amount_egp", nullable = false, precision = 19, scale = 4)
    private BigDecimal targetAmountEgp;

    @Column(name = "executed_shares", nullable = false)
    private Long executedShares;

    @Column(name = "settlement_date")
    private LocalDate settlementDate;

    @Enumerated(EnumType.STRING)
    @Column(name = "settlement_status", nullable = false, length = 16)
    private SettlementStatus settlementStatus;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public Long getPortfolioRunId() {
        return portfolioRunId;
    }

    public void setPortfolioRunId(Long portfolioRunId) {
        this.portfolioRunId = portfolioRunId;
    }

    public Long getStockId() {
        return stockId;
    }

    public void setStockId(Long stockId) {
        this.stockId = stockId;
    }

    public BigDecimal getPriceSnapshot() {
        return priceSnapshot;
    }

    public void setPriceSnapshot(BigDecimal priceSnapshot) {
        this.priceSnapshot = priceSnapshot;
    }

    public BigDecimal getTargetAmountEgp() {
        return targetAmountEgp;
    }

    public void setTargetAmountEgp(BigDecimal targetAmountEgp) {
        this.targetAmountEgp = targetAmountEgp;
    }

    public Long getExecutedShares() {
        return executedShares;
    }

    public void setExecutedShares(Long executedShares) {
        this.executedShares = executedShares;
    }

    /**
     * Calculate executed amount on-demand (5NF compliance).
     * Formula: executed_shares * price_snapshot
     */
    public BigDecimal getExecutedAmountEgp() {
        if (executedShares == null || priceSnapshot == null) {
            return BigDecimal.ZERO;
        }
        return priceSnapshot.multiply(BigDecimal.valueOf(executedShares));
    }

    /**
     * Calculate residual component on-demand (5NF compliance).
     * Formula: target_amount_egp - executed_amount_egp
     */
    public BigDecimal getResidualComponentEgp() {
        if (targetAmountEgp == null) {
            return BigDecimal.ZERO;
        }
        return targetAmountEgp.subtract(getExecutedAmountEgp());
    }

    public LocalDate getSettlementDate() {
        return settlementDate;
    }

    public void setSettlementDate(LocalDate settlementDate) {
        this.settlementDate = settlementDate;
    }

    public SettlementStatus getSettlementStatus() {
        return settlementStatus;
    }

    public void setSettlementStatus(SettlementStatus settlementStatus) {
        this.settlementStatus = settlementStatus;
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(LocalDateTime createdAt) {
        this.createdAt = createdAt;
    }

}