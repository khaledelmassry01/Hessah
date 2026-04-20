package com.egx.core.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;

import com.egx.core.domain.StopRule;

public interface StopRuleRepository extends JpaRepository<StopRule, Long> {
    List<StopRule> findByIsActiveTrue();

    List<StopRule> findByUserIdOrderByUpdatedAtDesc(Long userId);
}
