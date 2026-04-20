package com.egx.core.repository;

import com.egx.core.domain.UserSession;
import org.springframework.data.jpa.repository.JpaRepository;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

public interface UserSessionRepository extends JpaRepository<UserSession, Long> {

    Optional<UserSession> findFirstByUserIdAndRefreshTokenJtiAndIsRevokedFalseAndExpiresAtAfter(
            Long userId,
            String refreshTokenJti,
            LocalDateTime threshold
    );

    boolean existsByUserIdAndRefreshTokenJtiAndIsRevokedFalseAndExpiresAtAfter(
            Long userId,
            String refreshTokenJti,
            LocalDateTime threshold
    );

    Optional<UserSession> findByIdAndUserId(Long id, Long userId);

    List<UserSession> findByUserIdAndIsRevokedFalseAndExpiresAtAfterOrderByLastActiveDesc(
            Long userId,
            LocalDateTime threshold
    );

    List<UserSession> findByUserIdAndIsRevokedFalse(Long userId);
}
