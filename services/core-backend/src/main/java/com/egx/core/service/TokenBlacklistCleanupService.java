package com.egx.core.service;

import com.egx.core.repository.TokenBlacklistRepository;
import jakarta.transaction.Transactional;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.time.ZoneOffset;

@Service
public class TokenBlacklistCleanupService {

    private final TokenBlacklistRepository tokenBlacklistRepository;

    public TokenBlacklistCleanupService(TokenBlacklistRepository tokenBlacklistRepository) {
        this.tokenBlacklistRepository = tokenBlacklistRepository;
    }

    @Scheduled(cron = "${app.security.token-blacklist-cleanup-cron:0 0 3 * * *}")
    @Transactional
    public void cleanupExpiredTokens() {
        tokenBlacklistRepository.deleteByExpiresAtBefore(LocalDateTime.now(ZoneOffset.UTC));
    }
}
