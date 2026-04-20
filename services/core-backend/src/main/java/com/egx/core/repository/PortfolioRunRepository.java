package com.egx.core.repository;

import java.util.Collection;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;

import com.egx.core.domain.PortfolioRun;
import com.egx.core.domain.enums.PortfolioRunStatus;

public interface PortfolioRunRepository extends JpaRepository<PortfolioRun, Long> {
    Optional<PortfolioRun> findByRequestUuid(String requestUuid);

    Optional<PortfolioRun> findByIdAndUserId(Long id, Long userId);

    Optional<PortfolioRun> findTopByUserIdOrderByGeneratedAtDescIdDesc(Long userId);

    Optional<PortfolioRun> findFirstByUserIdAndRunStatusInOrderByGeneratedAtDescIdDesc(
            Long userId,
            Collection<PortfolioRunStatus> runStatuses
    );
}
