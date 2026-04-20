package com.egx.core.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.math.BigDecimal;
import java.time.LocalDate;

@Entity
@Table(name = "liquidity_snapshots")
public class LiquiditySnapshot {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "stock_id", nullable = false)
    private Long stockId;

    @Column(name = "as_of_date", nullable = false)
    private LocalDate asOfDate;

    @Column(name = "adv30_shares", nullable = false)
    private Long adv30Shares;

    @Column(name = "adv30_value_egp", nullable = false, precision = 19, scale = 4)
    private BigDecimal adv30ValueEgp;

    @Column(name = "max_allocatable_value_egp", nullable = false, precision = 19, scale = 4)
    private BigDecimal maxAllocatableValueEgp;

    @Column(length = 128)
    private String source;

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public Long getStockId() {
        return stockId;
    }

    public void setStockId(Long stockId) {
        this.stockId = stockId;
    }

    public LocalDate getAsOfDate() {
        return asOfDate;
    }

    public void setAsOfDate(LocalDate asOfDate) {
        this.asOfDate = asOfDate;
    }

    public Long getAdv30Shares() {
        return adv30Shares;
    }

    public void setAdv30Shares(Long adv30Shares) {
        this.adv30Shares = adv30Shares;
    }

    public BigDecimal getAdv30ValueEgp() {
        return adv30ValueEgp;
    }

    public void setAdv30ValueEgp(BigDecimal adv30ValueEgp) {
        this.adv30ValueEgp = adv30ValueEgp;
    }

    public BigDecimal getMaxAllocatableValueEgp() {
        return maxAllocatableValueEgp;
    }

    public void setMaxAllocatableValueEgp(BigDecimal maxAllocatableValueEgp) {
        this.maxAllocatableValueEgp = maxAllocatableValueEgp;
    }

    public String getSource() {
        return source;
    }

    public void setSource(String source) {
        this.source = source;
    }

}