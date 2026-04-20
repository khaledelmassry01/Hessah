package com.egx.core.domain;

import com.egx.core.domain.enums.RebalanceAlertStatus;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

@Entity
@Table(name = "rebalance_alerts")
public class RebalanceAlert {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "portfolio_run_id", nullable = false)
    private Long portfolioRunId;

    @Column(name = "as_of_date", nullable = false)
    private LocalDate asOfDate;

    @Column(name = "total_drift_pct", nullable = false, precision = 6, scale = 3)
    private BigDecimal totalDriftPct;

    @Column(name = "recommendation_json", nullable = false, columnDefinition = "json")
    private String recommendationJson;

    @Enumerated(EnumType.STRING)
    @Column(name = "alert_status", nullable = false, length = 16)
    private RebalanceAlertStatus alertStatus;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public Long getUserId() {
        return userId;
    }

    public void setUserId(Long userId) {
        this.userId = userId;
    }

    public Long getPortfolioRunId() {
        return portfolioRunId;
    }

    public void setPortfolioRunId(Long portfolioRunId) {
        this.portfolioRunId = portfolioRunId;
    }

    public LocalDate getAsOfDate() {
        return asOfDate;
    }

    public void setAsOfDate(LocalDate asOfDate) {
        this.asOfDate = asOfDate;
    }

    public BigDecimal getTotalDriftPct() {
        return totalDriftPct;
    }

    public void setTotalDriftPct(BigDecimal totalDriftPct) {
        this.totalDriftPct = totalDriftPct;
    }

    public String getRecommendationJson() {
        return recommendationJson;
    }

    public void setRecommendationJson(String recommendationJson) {
        this.recommendationJson = recommendationJson;
    }

    public RebalanceAlertStatus getAlertStatus() {
        return alertStatus;
    }

    public void setAlertStatus(RebalanceAlertStatus alertStatus) {
        this.alertStatus = alertStatus;
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(LocalDateTime createdAt) {
        this.createdAt = createdAt;
    }

}