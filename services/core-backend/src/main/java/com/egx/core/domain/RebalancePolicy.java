package com.egx.core.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Entity
@Table(name = "rebalance_policies")
public class RebalancePolicy {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false, unique = true)
    private Long userId;

    @Column(name = "drift_threshold_pct", nullable = false, precision = 6, scale = 3)
    private BigDecimal driftThresholdPct;

    @Column(name = "auto_rebalance_enabled", nullable = false)
    private Boolean autoRebalanceEnabled;

    @Column(nullable = false)
    private Boolean enabled;

    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt;

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

    public BigDecimal getDriftThresholdPct() {
        return driftThresholdPct;
    }

    public void setDriftThresholdPct(BigDecimal driftThresholdPct) {
        this.driftThresholdPct = driftThresholdPct;
    }

    public Boolean getAutoRebalanceEnabled() {
        return autoRebalanceEnabled;
    }

    public void setAutoRebalanceEnabled(Boolean autoRebalanceEnabled) {
        this.autoRebalanceEnabled = autoRebalanceEnabled;
    }

    public Boolean getEnabled() {
        return enabled;
    }

    public void setEnabled(Boolean enabled) {
        this.enabled = enabled;
    }

    public LocalDateTime getUpdatedAt() {
        return updatedAt;
    }

    public void setUpdatedAt(LocalDateTime updatedAt) {
        this.updatedAt = updatedAt;
    }

}