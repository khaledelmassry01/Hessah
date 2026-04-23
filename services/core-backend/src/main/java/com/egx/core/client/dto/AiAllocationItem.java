package com.egx.core.client.dto;

import java.math.BigDecimal;

import com.fasterxml.jackson.annotation.JsonProperty;

public class AiAllocationItem {

    @JsonProperty("symbol")
    private String symbol;
    @JsonProperty("weight")
    private BigDecimal weight;
    @JsonProperty("sector")
    private String sector;
    @JsonProperty("predicted_return_5d")
    private BigDecimal predictedReturn5d;
    @JsonProperty("confidence_score")
    private BigDecimal confidenceScore;

    public String getSymbol() {
        return symbol;
    }

    public void setSymbol(String symbol) {
        this.symbol = symbol;
    }

    public BigDecimal getWeight() {
        return weight;
    }

    public void setWeight(BigDecimal weight) {
        this.weight = weight;
    }

    public String getSector() {
        return sector;
    }

    public void setSector(String sector) {
        this.sector = sector;
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
