package com.egx.core.repository;

import java.util.Optional;
import java.util.Set;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import com.egx.core.domain.Permission;

@Repository
public interface PermissionRepository extends JpaRepository<Permission, Integer> {
    Optional<Permission> findByName(String name);
    
    boolean existsByName(String name);
    
    Set<Permission> findByNameIn(Set<String> names);
}
