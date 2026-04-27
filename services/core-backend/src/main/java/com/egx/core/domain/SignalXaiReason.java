package com.egx.core.domain;

import java.math.BigDecimal;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.Table;

@Entity
@Table(
    name = "signal_xai_reasons",
    indexes = {
        @Index(name = "idx_signal_xai_reasons_signal_id", columnList = "signal_id")
    }
)
public class SignalXaiReason {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "signal_id", nullable = false)
    private Long signalId;

    @Column(name = "reason_order", nullable = false)
    private Integer reasonOrder;

    @Column(name = "reason_text", nullable = false, length = 500)
    private String reasonText;

    @Column(name = "reason_weight", precision = 6, scale = 4)
    private BigDecimal reasonWeight;

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public Long getSignalId() {
        return signalId;
    }

    public void setSignalId(Long signalId) {
        this.signalId = signalId;
    }

    public Integer getReasonOrder() {
        return reasonOrder;
    }

    public void setReasonOrder(Integer reasonOrder) {
        this.reasonOrder = reasonOrder;
    }

    public String getReasonText() {
        return reasonText;
    }

    public void setReasonText(String reasonText) {
        this.reasonText = reasonText;
    }

    public BigDecimal getReasonWeight() {
        return reasonWeight;
    }

    public void setReasonWeight(BigDecimal reasonWeight) {
        this.reasonWeight = reasonWeight;
    }
}
