package com.egx.core.domain;

import com.egx.core.domain.enums.RiskLevel;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Entity
@Table(name = "risk_profiles")
public class RiskProfile {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, unique = true, length = 16)
    private RiskLevel code;

    @Column(nullable = false, length = 255)
    private String description;

    @Column(name = "max_sector_weight", nullable = false, precision = 6, scale = 4)
    private BigDecimal maxSectorWeight;

    @Column(name = "max_adv30_participation", nullable = false, precision = 6, scale = 4)
    private BigDecimal maxAdv30Participation;

    @Column(name = "premium_required", nullable = false)
    private Boolean premiumRequired;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt;

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public RiskLevel getCode() {
        return code;
    }

    public void setCode(RiskLevel code) {
        this.code = code;
    }

    public String getDescription() {
        return description;
    }

    public void setDescription(String description) {
        this.description = description;
    }

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

    public Boolean getPremiumRequired() {
        return premiumRequired;
    }

    public void setPremiumRequired(Boolean premiumRequired) {
        this.premiumRequired = premiumRequired;
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