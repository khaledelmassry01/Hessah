package com.egx.core.repository;

import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;

import com.egx.core.domain.SectorReference;

public interface SectorReferenceRepository extends JpaRepository<SectorReference, String> {
    Optional<SectorReference> findByCodeIgnoreCase(String code);
}
