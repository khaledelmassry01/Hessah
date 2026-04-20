package com.egx.core.repository;

import com.egx.core.domain.PortfolioRun;
import com.egx.core.domain.enums.PortfolioRunStatus;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface PortfolioRunRepository extends JpaRepository<PortfolioRun, Long> {
    Optional<PortfolioRun> findByRequestUuid(String requestUuid);

    Optional<PortfolioRun> findByIdAndUserId(Long id, Long userId);

    Optional<PortfolioRun> findTopByUserIdOrderByGeneratedAtDescIdDesc(Long userId);

    Optional<PortfolioRun> findFirstByUserIdAndRunStatusOrderByGeneratedAtDescIdDesc(
            Long userId,
            PortfolioRunStatus runStatus
    );
}
