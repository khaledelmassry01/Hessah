package com.egx.core.client.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.math.BigDecimal;

public class AiBacktestAllocationItem {

    private String symbol;
    private String sector;
    private BigDecimal weight;

    @JsonProperty("historical_price")
    private BigDecimal historicalPrice;

    @JsonProperty("current_price")
    private BigDecimal currentPrice;

    private BigDecimal shares;

    @JsonProperty("allocated_value_egp")
    private BigDecimal allocatedValueEgp;

    @JsonProperty("current_value_egp")
    private BigDecimal currentValueEgp;

    public String getSymbol() {
        return symbol;
    }

    public void setSymbol(String symbol) {
        this.symbol = symbol;
    }

    public String getSector() {
        return sector;
    }

    public void setSector(String sector) {
        this.sector = sector;
    }

    public BigDecimal getWeight() {
        return weight;
    }

    public void setWeight(BigDecimal weight) {
        this.weight = weight;
    }

    public BigDecimal getHistoricalPrice() {
        return historicalPrice;
    }

    public void setHistoricalPrice(BigDecimal historicalPrice) {
        this.historicalPrice = historicalPrice;
    }

    public BigDecimal getCurrentPrice() {
        return currentPrice;
    }

    public void setCurrentPrice(BigDecimal currentPrice) {
        this.currentPrice = currentPrice;
    }

    public BigDecimal getShares() {
        return shares;
    }

    public void setShares(BigDecimal shares) {
        this.shares = shares;
    }

    public BigDecimal getAllocatedValueEgp() {
        return allocatedValueEgp;
    }

    public void setAllocatedValueEgp(BigDecimal allocatedValueEgp) {
        this.allocatedValueEgp = allocatedValueEgp;
    }

    public BigDecimal getCurrentValueEgp() {
        return currentValueEgp;
    }

    public void setCurrentValueEgp(BigDecimal currentValueEgp) {
        this.currentValueEgp = currentValueEgp;
    }
}
