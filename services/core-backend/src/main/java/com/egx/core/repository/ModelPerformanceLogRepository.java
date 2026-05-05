package com.egx.core.repository;

import java.util.List;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import com.egx.core.domain.ModelPerformanceLog;

public interface ModelPerformanceLogRepository extends JpaRepository<ModelPerformanceLog, Long> {
    List<ModelPerformanceLog> findTop200ByRiskLevelOrderByCreatedAtDesc(String riskLevel);

    List<ModelPerformanceLog> findByOrderByCreatedAtDesc(Pageable pageable);

    List<ModelPerformanceLog> findByUserIdOrderByCreatedAtDesc(Long userId, Pageable pageable);
}
