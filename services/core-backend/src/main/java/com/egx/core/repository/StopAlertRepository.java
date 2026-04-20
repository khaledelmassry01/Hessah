package com.egx.core.repository;

import com.egx.core.domain.StopAlert;
import com.egx.core.domain.enums.StopTriggerType;
import org.springframework.data.jpa.repository.JpaRepository;

import java.time.LocalDateTime;

public interface StopAlertRepository extends JpaRepository<StopAlert, Long> {
    boolean existsByStopRuleIdAndTriggerTypeAndTriggeredAtBetween(
            Long stopRuleId,
            StopTriggerType triggerType,
            LocalDateTime start,
            LocalDateTime end
    );
}
