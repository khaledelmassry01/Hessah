package com.egx.core.client.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.math.BigDecimal;

public class AiConstraintsPayload {

    @JsonProperty("max_sector_weight")
    private BigDecimal maxSectorWeight;

    @JsonProperty("max_adv30_participation")
    private BigDecimal maxAdv30Participation;

    @JsonProperty("exclude_suspended")
    private boolean excludeSuspended;

    @JsonProperty("allow_fractional_shares")
    private boolean allowFractionalShares;

    public BigDecimal getMaxSectorWeight() {
        return maxSectorWeight;
    }

    public void setMaxSectorWeight(BigDecimal maxSectorWeight) {
        this.maxSectorWeight = maxSectorWeight;
    }

    public BigDecimal getMaxAdv30Participation() {
        return maxAdv30Participation;
    }

    public void setMaxAdv30Participation(BigDecimal maxAdv30Participation) {
        this.maxAdv30Participation = maxAdv30Participation;
    }

    public boolean isExcludeSuspended() {
        return excludeSuspended;
    }

    public void setExcludeSuspended(boolean excludeSuspended) {
        this.excludeSuspended = excludeSuspended;
    }

    public boolean isAllowFractionalShares() {
        return allowFractionalShares;
    }

    public void setAllowFractionalShares(boolean allowFractionalShares) {
        this.allowFractionalShares = allowFractionalShares;
    }
}
