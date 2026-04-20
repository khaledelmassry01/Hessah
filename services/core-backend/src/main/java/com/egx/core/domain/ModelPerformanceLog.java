package com.egx.core.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

@Entity
@Table(name = "model_performance_logs")
public class ModelPerformanceLog {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "request_id", length = 64)
    private String requestId;

    @Column(name = "user_id")
    private Long userId;

    @Column(name = "risk_level", nullable = false, length = 16)
    private String riskLevel;

    @Column(name = "model_version", nullable = false, length = 64)
    private String modelVersion;

    @Column(name = "historical_date", nullable = false)
    private LocalDate historicalDate;

    @Column(name = "evaluation_date", nullable = false)
    private LocalDate evaluationDate;

    @Column(name = "horizon_days", nullable = false)
    private Integer horizonDays;

    @Column(name = "budget_egp", nullable = false, precision = 19, scale = 4)
    private BigDecimal budgetEgp;

    @Column(name = "predicted_return", nullable = false, precision = 12, scale = 8)
    private BigDecimal predictedReturn;

    @Column(name = "actual_return", nullable = false, precision = 12, scale = 8)
    private BigDecimal actualReturn;

    @Column(name = "prediction_error", nullable = false, precision = 12, scale = 8)
    private BigDecimal predictionError;

    @Column(name = "risk_free_rate", nullable = false, precision = 8, scale = 6)
    private BigDecimal riskFreeRate;

    @Column(name = "covariance_shrinkage", nullable = false, precision = 8, scale = 6)
    private BigDecimal covarianceShrinkage;

    @Column(name = "run_status", nullable = false, length = 16)
    private String runStatus;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getRequestId() {
        return requestId;
    }

    public void setRequestId(String requestId) {
        this.requestId = requestId;
    }

    public Long getUserId() {
        return userId;
    }

    public void setUserId(Long userId) {
        this.userId = userId;
    }

    public String getRiskLevel() {
        return riskLevel;
    }

    public void setRiskLevel(String riskLevel) {
        this.riskLevel = riskLevel;
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

    public LocalDate getEvaluationDate() {
        return evaluationDate;
    }

    public void setEvaluationDate(LocalDate evaluationDate) {
        this.evaluationDate = evaluationDate;
    }

    public Integer getHorizonDays() {
        return horizonDays;
    }

    public void setHorizonDays(Integer horizonDays) {
        this.horizonDays = horizonDays;
    }

    public BigDecimal getBudgetEgp() {
        return budgetEgp;
    }

    public void setBudgetEgp(BigDecimal budgetEgp) {
        this.budgetEgp = budgetEgp;
    }

    public BigDecimal getPredictedReturn() {
        return predictedReturn;
    }

    public void setPredictedReturn(BigDecimal predictedReturn) {
        this.predictedReturn = predictedReturn;
    }

    public BigDecimal getActualReturn() {
        return actualReturn;
    }

    public void setActualReturn(BigDecimal actualReturn) {
        this.actualReturn = actualReturn;
    }

    public BigDecimal getPredictionError() {
        return predictionError;
    }

    public void setPredictionError(BigDecimal predictionError) {
        this.predictionError = predictionError;
    }

    public BigDecimal getRiskFreeRate() {
        return riskFreeRate;
    }

    public void setRiskFreeRate(BigDecimal riskFreeRate) {
        this.riskFreeRate = riskFreeRate;
    }

    public BigDecimal getCovarianceShrinkage() {
        return covarianceShrinkage;
    }

    public void setCovarianceShrinkage(BigDecimal covarianceShrinkage) {
        this.covarianceShrinkage = covarianceShrinkage;
    }

    public String getRunStatus() {
        return runStatus;
    }

    public void setRunStatus(String runStatus) {
        this.runStatus = runStatus;
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(LocalDateTime createdAt) {
        this.createdAt = createdAt;
    }
}
