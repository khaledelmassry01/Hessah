package com.egx.core.client.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.math.BigDecimal;
import java.time.LocalDate;

public class AiBacktestRequest {

    @JsonProperty("request_id")
    private String requestId;

    @JsonProperty("user_id")
    private String userId;

    @JsonProperty("budget_egp")
    private BigDecimal budgetEgp;

    @JsonProperty("historical_date")
    private LocalDate historicalDate;

    @JsonProperty("risk_level")
    private String riskLevel;

    private String tier;

    private AiConstraintsPayload constraints;

    public String getRequestId() {
        return requestId;
    }

    public void setRequestId(String requestId) {
        this.requestId = requestId;
    }

    public String getUserId() {
        return userId;
    }

    public void setUserId(String userId) {
        this.userId = userId;
    }

    public BigDecimal getBudgetEgp() {
        return budgetEgp;
    }

    public void setBudgetEgp(BigDecimal budgetEgp) {
        this.budgetEgp = budgetEgp;
    }

    public LocalDate getHistoricalDate() {
        return historicalDate;
    }

    public void setHistoricalDate(LocalDate historicalDate) {
        this.historicalDate = historicalDate;
    }

    public String getRiskLevel() {
        return riskLevel;
    }

    public void setRiskLevel(String riskLevel) {
        this.riskLevel = riskLevel;
    }

    public String getTier() {
        return tier;
    }

    public void setTier(String tier) {
        this.tier = tier;
    }

    public AiConstraintsPayload getConstraints() {
        return constraints;
    }

    public void setConstraints(AiConstraintsPayload constraints) {
        this.constraints = constraints;
    }
}
