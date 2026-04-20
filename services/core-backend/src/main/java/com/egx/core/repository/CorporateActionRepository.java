package com.egx.core.repository;

import com.egx.core.domain.CorporateAction;
import com.egx.core.domain.enums.IngestionStatus;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface CorporateActionRepository extends JpaRepository<CorporateAction, Long> {
    List<CorporateAction> findByIngestionStatus(IngestionStatus ingestionStatus);
}
