package com.egx.core.domain;

import com.egx.core.domain.enums.SettlementStatus;
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
@Table(name = "position_lots")
public class PositionLot {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "stock_id", nullable = false)
    private Long stockId;

    @Column(name = "source_order_id", nullable = false)
    private Long sourceOrderId;

    @Column(name = "quantity_total", nullable = false)
    private Long quantityTotal;

    @Column(name = "quantity_available", nullable = false)
    private Long quantityAvailable;

    @Column(name = "avg_cost", nullable = false, precision = 19, scale = 4)
    private BigDecimal avgCost;

    @Column(name = "acquisition_date", nullable = false)
    private LocalDate acquisitionDate;

    @Column(name = "settlement_date", nullable = false)
    private LocalDate settlementDate;

    @Enumerated(EnumType.STRING)
    @Column(name = "settlement_status", nullable = false, length = 16)
    private SettlementStatus settlementStatus;

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

    public Long getStockId() {
        return stockId;
    }

    public void setStockId(Long stockId) {
        this.stockId = stockId;
    }

    public Long getSourceOrderId() {
        return sourceOrderId;
    }

    public void setSourceOrderId(Long sourceOrderId) {
        this.sourceOrderId = sourceOrderId;
    }

    public Long getQuantityTotal() {
        return quantityTotal;
    }

    public void setQuantityTotal(Long quantityTotal) {
        this.quantityTotal = quantityTotal;
    }

    public Long getQuantityAvailable() {
        return quantityAvailable;
    }

    public void setQuantityAvailable(Long quantityAvailable) {
        this.quantityAvailable = quantityAvailable;
    }

    public BigDecimal getAvgCost() {
        return avgCost;
    }

    public void setAvgCost(BigDecimal avgCost) {
        this.avgCost = avgCost;
    }

    public LocalDate getAcquisitionDate() {
        return acquisitionDate;
    }

    public void setAcquisitionDate(LocalDate acquisitionDate) {
        this.acquisitionDate = acquisitionDate;
    }

    public LocalDate getSettlementDate() {
        return settlementDate;
    }

    public void setSettlementDate(LocalDate settlementDate) {
        this.settlementDate = settlementDate;
    }

    public SettlementStatus getSettlementStatus() {
        return settlementStatus;
    }

    public void setSettlementStatus(SettlementStatus settlementStatus) {
        this.settlementStatus = settlementStatus;
    }

    public LocalDateTime getUpdatedAt() {
        return updatedAt;
    }

    public void setUpdatedAt(LocalDateTime updatedAt) {
        this.updatedAt = updatedAt;
    }

}