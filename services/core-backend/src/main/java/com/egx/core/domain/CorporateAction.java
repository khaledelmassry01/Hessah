package com.egx.core.domain;

import com.egx.core.domain.enums.CorporateActionType;
import com.egx.core.domain.enums.IngestionStatus;
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
@Table(name = "corporate_actions")
public class CorporateAction {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "stock_id", nullable = false)
    private Long stockId;

    @Enumerated(EnumType.STRING)
    @Column(name = "action_type", nullable = false, length = 16)
    private CorporateActionType actionType;

    @Column(name = "ex_date", nullable = false)
    private LocalDate exDate;

    @Column(name = "record_date")
    private LocalDate recordDate;

    @Column(name = "payable_date")
    private LocalDate payableDate;

    @Column(name = "split_from")
    private Integer splitFrom;

    @Column(name = "split_to")
    private Integer splitTo;

    @Column(name = "cash_dividend_per_share", precision = 19, scale = 6)
    private BigDecimal cashDividendPerShare;

    @Enumerated(EnumType.STRING)
    @Column(name = "ingestion_status", nullable = false, length = 16)
    private IngestionStatus ingestionStatus;

    @Column(name = "processed_at")
    private LocalDateTime processedAt;

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

    public CorporateActionType getActionType() {
        return actionType;
    }

    public void setActionType(CorporateActionType actionType) {
        this.actionType = actionType;
    }

    public LocalDate getExDate() {
        return exDate;
    }

    public void setExDate(LocalDate exDate) {
        this.exDate = exDate;
    }

    public LocalDate getRecordDate() {
        return recordDate;
    }

    public void setRecordDate(LocalDate recordDate) {
        this.recordDate = recordDate;
    }

    public LocalDate getPayableDate() {
        return payableDate;
    }

    public void setPayableDate(LocalDate payableDate) {
        this.payableDate = payableDate;
    }

    public Integer getSplitFrom() {
        return splitFrom;
    }

    public void setSplitFrom(Integer splitFrom) {
        this.splitFrom = splitFrom;
    }

    public Integer getSplitTo() {
        return splitTo;
    }

    public void setSplitTo(Integer splitTo) {
        this.splitTo = splitTo;
    }

    public BigDecimal getCashDividendPerShare() {
        return cashDividendPerShare;
    }

    public void setCashDividendPerShare(BigDecimal cashDividendPerShare) {
        this.cashDividendPerShare = cashDividendPerShare;
    }

    public IngestionStatus getIngestionStatus() {
        return ingestionStatus;
    }

    public void setIngestionStatus(IngestionStatus ingestionStatus) {
        this.ingestionStatus = ingestionStatus;
    }

    public LocalDateTime getProcessedAt() {
        return processedAt;
    }

    public void setProcessedAt(LocalDateTime processedAt) {
        this.processedAt = processedAt;
    }

}