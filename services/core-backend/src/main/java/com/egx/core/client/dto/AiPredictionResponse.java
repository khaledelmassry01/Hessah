package com.egx.core.client.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

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

    private List<AiAllocationItem> allocations = new ArrayList<>();

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

    public List<AiAllocationItem> getAllocations() {
        return allocations;
    }

    public void setAllocations(List<AiAllocationItem> allocations) {
        this.allocations = allocations;
    }

    public List<String> getWarnings() {
        return warnings;
    }

    public void setWarnings(List<String> warnings) {
        this.warnings = warnings;
    }
}
