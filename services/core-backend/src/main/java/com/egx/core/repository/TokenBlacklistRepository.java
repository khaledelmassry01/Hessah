package com.egx.core.repository;

import com.egx.core.domain.TokenBlacklist;
import org.springframework.data.jpa.repository.JpaRepository;

import java.time.LocalDateTime;
import java.util.Optional;

public interface TokenBlacklistRepository extends JpaRepository<TokenBlacklist, Long> {

    boolean existsByToken(String token);

    Optional<TokenBlacklist> findByToken(String token);

    long deleteByExpiresAtBefore(LocalDateTime threshold);
}
