package com.egx.core.client.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

public class AiBacktestResponse {

    @JsonProperty("request_id")
    private String requestId;

    private String status;

    @JsonProperty("model_version")
    private String modelVersion;

    @JsonProperty("historical_date")
    private LocalDate historicalDate;

    @JsonProperty("original_value_egp")
    private BigDecimal originalValueEgp;

    @JsonProperty("current_value_egp")
    private BigDecimal currentValueEgp;

    @JsonProperty("roi_pct")
    private BigDecimal roiPct;

    @JsonProperty("expected_return")
    private BigDecimal expectedReturn;

    @JsonProperty("expected_volatility")
    private BigDecimal expectedVolatility;

    @JsonProperty("historical_allocations")
    private List<AiBacktestAllocationItem> historicalAllocations = new ArrayList<>();

    @JsonProperty("rejected_symbols")
    private List<AiRejectedSymbolItem> rejectedSymbols = new ArrayList<>();

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

    public LocalDate getHistoricalDate() {
        return historicalDate;
    }

    public void setHistoricalDate(LocalDate historicalDate) {
        this.historicalDate = historicalDate;
    }

    public BigDecimal getOriginalValueEgp() {
        return originalValueEgp;
    }

    public void setOriginalValueEgp(BigDecimal originalValueEgp) {
        this.originalValueEgp = originalValueEgp;
    }

    public BigDecimal getCurrentValueEgp() {
        return currentValueEgp;
    }

    public void setCurrentValueEgp(BigDecimal currentValueEgp) {
        this.currentValueEgp = currentValueEgp;
    }

    public BigDecimal getRoiPct() {
        return roiPct;
    }

    public void setRoiPct(BigDecimal roiPct) {
        this.roiPct = roiPct;
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

    public List<AiBacktestAllocationItem> getHistoricalAllocations() {
        return historicalAllocations;
    }

    public void setHistoricalAllocations(List<AiBacktestAllocationItem> historicalAllocations) {
        this.historicalAllocations = historicalAllocations;
    }

    public List<AiRejectedSymbolItem> getRejectedSymbols() {
        return rejectedSymbols;
    }

    public void setRejectedSymbols(List<AiRejectedSymbolItem> rejectedSymbols) {
        this.rejectedSymbols = rejectedSymbols;
    }

    public List<String> getWarnings() {
        return warnings;
    }

    public void setWarnings(List<String> warnings) {
        this.warnings = warnings;
    }
}
