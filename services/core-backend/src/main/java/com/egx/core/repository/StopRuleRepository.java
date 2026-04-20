package com.egx.core.repository;

import com.egx.core.domain.StopRule;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface StopRuleRepository extends JpaRepository<StopRule, Long> {
    List<StopRule> findByIsActiveTrue();

    List<StopRule> findByUserIdOrderByUpdatedAtDesc(Long userId);
}
