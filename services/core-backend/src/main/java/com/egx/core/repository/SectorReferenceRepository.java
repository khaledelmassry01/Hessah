package com.egx.core.repository;

import com.egx.core.domain.SectorReference;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface SectorReferenceRepository extends JpaRepository<SectorReference, Long> {
    Optional<SectorReference> findByCodeIgnoreCase(String code);
}
