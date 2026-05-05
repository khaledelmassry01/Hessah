package com.egx.core.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import com.egx.core.domain.StopRule;

public interface StopRuleRepository extends JpaRepository<StopRule, Long> {
    List<StopRule> findByIsActiveTrue();

    List<StopRule> findByUserIdOrderByUpdatedAtDesc(Long userId);

    @Query("select sr from StopRule sr "
            + "where sr.userId = :userId "
            + "and sr.isActive = true "
            + "and sr.id in ("
            + "select max(sr2.id) from StopRule sr2 "
            + "where sr2.userId = :userId "
            + "and sr2.isActive = true "
            + "group by sr2.stockId) "
            + "order by sr.updatedAt desc")
    List<StopRule> findLatestActiveByUserId(@Param("userId") Long userId);
}
