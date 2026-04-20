package com.egx.core.repository;

import com.egx.core.domain.AiPredictionAudit;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface AiPredictionAuditRepository extends JpaRepository<AiPredictionAudit, Long> {
    Optional<AiPredictionAudit> findTopByPortfolioRunIdOrderByCreatedAtDesc(Long portfolioRunId);
}
