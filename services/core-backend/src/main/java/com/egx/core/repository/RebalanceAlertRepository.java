package com.egx.core.repository;

import com.egx.core.domain.RebalanceAlert;
import com.egx.core.domain.enums.RebalanceAlertStatus;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface RebalanceAlertRepository extends JpaRepository<RebalanceAlert, Long> {
    List<RebalanceAlert> findByUserIdAndAlertStatus(Long userId, RebalanceAlertStatus alertStatus);
}
