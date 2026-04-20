package com.egx.core.repository;

import com.egx.core.domain.ModelPerformanceLog;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface ModelPerformanceLogRepository extends JpaRepository<ModelPerformanceLog, Long> {
    List<ModelPerformanceLog> findTop200ByRiskLevelOrderByCreatedAtDesc(String riskLevel);

    List<ModelPerformanceLog> findByOrderByCreatedAtDesc(Pageable pageable);
}
