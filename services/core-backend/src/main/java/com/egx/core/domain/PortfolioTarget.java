package com.egx.core.domain;

import java.math.BigDecimal;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "portfolio_targets")
public class PortfolioTarget {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "portfolio_run_id", nullable = false)
    private Long portfolioRunId;

    @Column(name = "stock_id", nullable = false)
    private Long stockId;

    @Column(name = "target_weight", nullable = false, precision = 10, scale = 8)
    private BigDecimal targetWeight;

    @Column(name = "target_amount_egp", nullable = false, precision = 19, scale = 4)
    private BigDecimal targetAmountEgp;

    @Column(name = "constraint_flags_json", columnDefinition = "json")
    private String constraintFlagsJson;

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

    public BigDecimal getTargetWeight() {
        return targetWeight;
    }

    public void setTargetWeight(BigDecimal targetWeight) {
        this.targetWeight = targetWeight;
    }

    public BigDecimal getTargetAmountEgp() {
        return targetAmountEgp;
    }

    public void setTargetAmountEgp(BigDecimal targetAmountEgp) {
        this.targetAmountEgp = targetAmountEgp;
    }

    /**
     * Get sector code from associated stock instrument (5NF compliance).
     * This is a derived field, not stored in the table.
     */
    public String getSectorCode() {
        // This method can be populated via service layer using stock relationship
        return null; // To be populated via StockInstrument lookup in service
    }

    public String getConstraintFlagsJson() {
        return constraintFlagsJson;
    }

    public void setConstraintFlagsJson(String constraintFlagsJson) {
        this.constraintFlagsJson = constraintFlagsJson;
    }
}