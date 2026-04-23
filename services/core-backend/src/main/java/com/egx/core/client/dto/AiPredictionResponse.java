package com.egx.core.client.dto;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;

public class AiPredictionResponse {

    @JsonProperty("request_id")
    private String requestId;

    private String status;

    @JsonProperty("model_version")
    private String modelVersion;

    @JsonProperty("expected_return")
    private BigDecimal expectedReturn;

    @JsonProperty("expected_volatility")
    private BigDecimal expectedVolatility;

    @JsonProperty("predicted_return")
    private BigDecimal predictedReturn;

    @JsonProperty("confidence_score")
    private BigDecimal confidenceScore;

    @JsonProperty("model_accuracy")
    private BigDecimal modelAccuracy;

    @JsonProperty("allocations")
    private List<AiAllocationItem> allocations = new ArrayList<>();

    @JsonProperty("recommendations")
    private List<AiRecommendationItem> recommendations = new ArrayList<>();

    @JsonProperty("warnings")
    private List<String> warnings = new ArrayList<>();

    public String getRequestId() {
        return requestId;
    }

    public void setRequestId(String requestId) {
        this.requestId = requestId;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public String getModelVersion() {
        return modelVersion;
    }

    public void setModelVersion(String modelVersion) {
        this.modelVersion = modelVersion;
    }

    public BigDecimal getExpectedReturn() {
        return expectedReturn;
    }

    public void setExpectedReturn(BigDecimal expectedReturn) {
        this.expectedReturn = expectedReturn;
    }

    public BigDecimal getExpectedVolatility() {
        return expectedVolatility;
    }

    public void setExpectedVolatility(BigDecimal expectedVolatility) {
        this.expectedVolatility = expectedVolatility;
    }

    public BigDecimal getPredictedReturn() {
        return predictedReturn;
    }

    public void setPredictedReturn(BigDecimal predictedReturn) {
        this.predictedReturn = predictedReturn;
    }

    public BigDecimal getConfidenceScore() {
        return confidenceScore;
    }

    public void setConfidenceScore(BigDecimal confidenceScore) {
        this.confidenceScore = confidenceScore;
    }

    public BigDecimal getModelAccuracy() {
        return modelAccuracy;
    }

    public void setModelAccuracy(BigDecimal modelAccuracy) {
        this.modelAccuracy = modelAccuracy;
    }

    public List<AiAllocationItem> getAllocations() {
        return allocations;
    }

    public void setAllocations(List<AiAllocationItem> allocations) {
        this.allocations = allocations;
    }

    public List<AiRecommendationItem> getRecommendations() {
        return recommendations;
    }

    public void setRecommendations(List<AiRecommendationItem> recommendations) {
        this.recommendations = recommendations;
    }

    public List<String> getWarnings() {
        return warnings;
    }

    public void setWarnings(List<String> warnings) {
        this.warnings = warnings;
    }
}
