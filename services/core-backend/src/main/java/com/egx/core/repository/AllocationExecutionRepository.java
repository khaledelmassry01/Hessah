package com.egx.core.repository;

import com.egx.core.domain.AllocationExecution;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface AllocationExecutionRepository extends JpaRepository<AllocationExecution, Long> {
    List<AllocationExecution> findByPortfolioRunId(Long portfolioRunId);
}
