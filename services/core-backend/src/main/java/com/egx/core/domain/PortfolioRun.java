package com.egx.core.domain;

import com.egx.core.domain.enums.PortfolioRunStatus;
import com.egx.core.domain.enums.RiskLevel;
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
@Table(name = "portfolio_runs")
public class PortfolioRun {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "request_uuid", nullable = false, unique = true, length = 36, columnDefinition = "char(36)")
    private String requestUuid;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Enumerated(EnumType.STRING)
    @Column(name = "risk_level", nullable = false, length = 16)
    private RiskLevel riskLevel;

    @Column(name = "requested_amount_egp", nullable = false, precision = 19, scale = 4)
    private BigDecimal requestedAmountEgp;

    @Column(name = "fee_buffer_rate", nullable = false, precision = 6, scale = 5)
    private BigDecimal feeBufferRate;

    @Column(name = "investable_budget_egp", nullable = false, precision = 19, scale = 4)
    private BigDecimal investableBudgetEgp;

    @Enumerated(EnumType.STRING)
    @Column(name = "run_status", nullable = false, length = 16)
    private PortfolioRunStatus runStatus;

    @Column(name = "model_version", length = 64)
    private String modelVersion;

    @Column(name = "generated_at", nullable = false)
    private LocalDateTime generatedAt;

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getRequestUuid() {
        return requestUuid;
    }

    public void setRequestUuid(String requestUuid) {
        this.requestUuid = requestUuid;
    }

    public Long getUserId() {
        return userId;
    }

    public void setUserId(Long userId) {
        this.userId = userId;
    }

    public RiskLevel getRiskLevel() {
        return riskLevel;
    }

    public void setRiskLevel(RiskLevel riskLevel) {
        this.riskLevel = riskLevel;
    }

    public BigDecimal getRequestedAmountEgp() {
        return requestedAmountEgp;
    }

    public void setRequestedAmountEgp(BigDecimal requestedAmountEgp) {
        this.requestedAmountEgp = requestedAmountEgp;
    }

    public BigDecimal getFeeBufferRate() {
        return feeBufferRate;
    }

    public void setFeeBufferRate(BigDecimal feeBufferRate) {
        this.feeBufferRate = feeBufferRate;
    }

    public BigDecimal getInvestableBudgetEgp() {
        return investableBudgetEgp;
    }

    public void setInvestableBudgetEgp(BigDecimal investableBudgetEgp) {
        this.investableBudgetEgp = investableBudgetEgp;
    }

    public PortfolioRunStatus getRunStatus() {
        return runStatus;
    }

    public void setRunStatus(PortfolioRunStatus runStatus) {
        this.runStatus = runStatus;
    }

    public String getModelVersion() {
        return modelVersion;
    }

    public void setModelVersion(String modelVersion) {
        this.modelVersion = modelVersion;
    }

    public LocalDateTime getGeneratedAt() {
        return generatedAt;
    }

    public void setGeneratedAt(LocalDateTime generatedAt) {
        this.generatedAt = generatedAt;
    }

}