package com.egx.core.client.dto;

import java.math.BigDecimal;

import com.fasterxml.jackson.annotation.JsonProperty;

public class AiRecommendationItem {

    @JsonProperty("symbol")
    private String symbol;
    @JsonProperty("action")
    private String action;
    @JsonProperty("reason")
    private String reason;

    @JsonProperty("predicted_return_5d")
    private BigDecimal predictedReturn5d;

    @JsonProperty("confidence_score")
    private BigDecimal confidenceScore;

    @JsonProperty("top_reasons")
    private java.util.List<String> topReasons;
    public java.util.List<String> getTopReasons() {
        return topReasons;
    }

    public void setTopReasons(java.util.List<String> topReasons) {
        this.topReasons = topReasons;
    }

    public String getSymbol() {
        return symbol;
    }

    public void setSymbol(String symbol) {
        this.symbol = symbol;
    }

    public String getAction() {
        return action;
    }

    public void setAction(String action) {
        this.action = action;
    }

    public String getReason() {
        return reason;
    }

    public void setReason(String reason) {
        this.reason = reason;
    }

    public BigDecimal getPredictedReturn5d() {
        return predictedReturn5d;
    }

    public void setPredictedReturn5d(BigDecimal predictedReturn5d) {
        this.predictedReturn5d = predictedReturn5d;
    }

    public BigDecimal getConfidenceScore() {
        return confidenceScore;
    }

    public void setConfidenceScore(BigDecimal confidenceScore) {
        this.confidenceScore = confidenceScore;
    }
}
