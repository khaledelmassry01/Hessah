package com.egx.core.repository;

import com.egx.core.domain.PortfolioTarget;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface PortfolioTargetRepository extends JpaRepository<PortfolioTarget, Long> {
    List<PortfolioTarget> findByPortfolioRunId(Long portfolioRunId);
}
