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
@Table(name = "market_daily_bars")
public class MarketDailyBar {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "stock_id", nullable = false)
    private Long stockId;

    @Column(name = "trade_date", nullable = false)
    private LocalDate tradeDate;

    @Column(name = "open_price", nullable = false, precision = 19, scale = 4)
    private BigDecimal openPrice;

    @Column(name = "high_price", nullable = false, precision = 19, scale = 4)
    private BigDecimal highPrice;

    @Column(name = "low_price", nullable = false, precision = 19, scale = 4)
    private BigDecimal lowPrice;

    @Column(name = "close_price", nullable = false, precision = 19, scale = 4)
    private BigDecimal closePrice;

    @Column(nullable = false)
    private Long volume;

    @Column(name = "is_halted", nullable = false)
    private Boolean isHalted;

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

    public LocalDate getTradeDate() {
        return tradeDate;
    }

    public void setTradeDate(LocalDate tradeDate) {
        this.tradeDate = tradeDate;
    }

    public BigDecimal getOpenPrice() {
        return openPrice;
    }

    public void setOpenPrice(BigDecimal openPrice) {
        this.openPrice = openPrice;
    }

    public BigDecimal getHighPrice() {
        return highPrice;
    }

    public void setHighPrice(BigDecimal highPrice) {
        this.highPrice = highPrice;
    }

    public BigDecimal getLowPrice() {
        return lowPrice;
    }

    public void setLowPrice(BigDecimal lowPrice) {
        this.lowPrice = lowPrice;
    }

    public BigDecimal getClosePrice() {
        return closePrice;
    }

    public void setClosePrice(BigDecimal closePrice) {
        this.closePrice = closePrice;
    }

    public Long getVolume() {
        return volume;
    }

    public void setVolume(Long volume) {
        this.volume = volume;
    }

    public Boolean getIsHalted() {
        return isHalted;
    }

    public void setIsHalted(Boolean isHalted) {
        this.isHalted = isHalted;
    }

}