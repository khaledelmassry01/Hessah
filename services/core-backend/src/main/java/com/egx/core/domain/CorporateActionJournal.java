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
@Table(name = "corporate_action_journal")
public class CorporateActionJournal {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "corporate_action_id", nullable = false)
    private Long corporateActionId;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "position_lot_id")
    private Long positionLotId;

    @Column(name = "quantity_before")
    private Long quantityBefore;

    @Column(name = "quantity_after")
    private Long quantityAfter;

    @Column(name = "avg_cost_before", precision = 19, scale = 4)
    private BigDecimal avgCostBefore;

    @Column(name = "avg_cost_after", precision = 19, scale = 4)
    private BigDecimal avgCostAfter;

    @Column(name = "cash_credited_egp", precision = 19, scale = 4)
    private BigDecimal cashCreditedEgp;

    @Column(name = "wallet_ledger_entry_id")
    private Long walletLedgerEntryId;

    @Column(name = "processed_at", nullable = false)
    private LocalDateTime processedAt;

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public Long getCorporateActionId() {
        return corporateActionId;
    }

    public void setCorporateActionId(Long corporateActionId) {
        this.corporateActionId = corporateActionId;
    }

    public Long getUserId() {
        return userId;
    }

    public void setUserId(Long userId) {
        this.userId = userId;
    }

    public Long getPositionLotId() {
        return positionLotId;
    }

    public void setPositionLotId(Long positionLotId) {
        this.positionLotId = positionLotId;
    }

    public Long getQuantityBefore() {
        return quantityBefore;
    }

    public void setQuantityBefore(Long quantityBefore) {
        this.quantityBefore = quantityBefore;
    }

    public Long getQuantityAfter() {
        return quantityAfter;
    }

    public void setQuantityAfter(Long quantityAfter) {
        this.quantityAfter = quantityAfter;
    }

    public BigDecimal getAvgCostBefore() {
        return avgCostBefore;
    }

    public void setAvgCostBefore(BigDecimal avgCostBefore) {
        this.avgCostBefore = avgCostBefore;
    }

    public BigDecimal getAvgCostAfter() {
        return avgCostAfter;
    }

    public void setAvgCostAfter(BigDecimal avgCostAfter) {
        this.avgCostAfter = avgCostAfter;
    }

    public BigDecimal getCashCreditedEgp() {
        return cashCreditedEgp;
    }

    public void setCashCreditedEgp(BigDecimal cashCreditedEgp) {
        this.cashCreditedEgp = cashCreditedEgp;
    }

    public Long getWalletLedgerEntryId() {
        return walletLedgerEntryId;
    }

    public void setWalletLedgerEntryId(Long walletLedgerEntryId) {
        this.walletLedgerEntryId = walletLedgerEntryId;
    }

    public LocalDateTime getProcessedAt() {
        return processedAt;
    }

    public void setProcessedAt(LocalDateTime processedAt) {
        this.processedAt = processedAt;
    }

}