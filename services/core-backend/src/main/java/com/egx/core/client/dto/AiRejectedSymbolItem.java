package com.egx.core.client.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public class AiRejectedSymbolItem {

    @JsonProperty("symbol")
    private String symbol;

    @JsonProperty("reason")
    private String reason;

    public String getSymbol() {
        return symbol;
    }

    public void setSymbol(String symbol) {
        this.symbol = symbol;
    }

    public String getReason() {
        return reason;
    }

    public void setReason(String reason) {
        this.reason = reason;
    }
}
