package com.egx.core.domain;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.Table;

/**
 * Daily AI Market Radar Signal - Stores latest AI predictions for active monitoring.
 * Updated daily at 4 PM by MarketRadarScheduler.
 */
@Entity
@Table(
    name = "daily_ai_signals",
    indexes = {
        @Index(name = "idx_daily_ai_signals_symbol", columnList = "symbol"),
        @Index(name = "idx_daily_ai_signals_signal_date", columnList = "signal_date"),
        @Index(name = "idx_daily_ai_signals_symbol_date", columnList = "symbol, signal_date", unique = true)
    }
)
public class DailyAiSignal {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "symbol", nullable = false, length = 16)
    private String symbol;

    @Column(name = "stock_id")
    private Long stockId;

    @Column(name = "signal_date", nullable = false)
    private LocalDate signalDate;

    @Column(name = "action", nullable = false, length = 20)
    private String action; // BUY, HOLD, SELL, PREVENTIVE_SELL

    @Column(name = "confidence_score", precision = 6, scale = 4)
    private BigDecimal confidenceScore;

    @Column(name = "predicted_return_5d", precision = 10, scale = 6)
    private BigDecimal predictedReturn5d;

    @Column(name = "model_version", length = 64)
    private String modelVersion;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt;

    // Getters and Setters

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getSymbol() {
        return symbol;
    }

    public void setSymbol(String symbol) {
        this.symbol = symbol;
    }

    public Long getStockId() {
        return stockId;
    }

    public void setStockId(Long stockId) {
        this.stockId = stockId;
    }

    public LocalDate getSignalDate() {
        return signalDate;
    }

    public void setSignalDate(LocalDate signalDate) {
        this.signalDate = signalDate;
    }

    public String getAction() {
        return action;
    }

    public void setAction(String action) {
        this.action = action;
    }

    public BigDecimal getConfidenceScore() {
        return confidenceScore;
    }

    public void setConfidenceScore(BigDecimal confidenceScore) {
        this.confidenceScore = confidenceScore;
    }

    public BigDecimal getPredictedReturn5d() {
        return predictedReturn5d;
    }

    public void setPredictedReturn5d(BigDecimal predictedReturn5d) {
        this.predictedReturn5d = predictedReturn5d;
    }

    public String getModelVersion() {
        return modelVersion;
    }

    public void setModelVersion(String modelVersion) {
        this.modelVersion = modelVersion;
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(LocalDateTime createdAt) {
        this.createdAt = createdAt;
    }

    public LocalDateTime getUpdatedAt() {
        return updatedAt;
    }

    public void setUpdatedAt(LocalDateTime updatedAt) {
        this.updatedAt = updatedAt;
    }
}
