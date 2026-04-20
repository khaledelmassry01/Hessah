package com.egx.core.service;

import com.egx.core.domain.UserSession;
import com.egx.core.repository.UserSessionRepository;
import com.egx.core.security.JwtService;
import jakarta.transaction.Transactional;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.List;

@Service
public class SessionService {

    private final UserSessionRepository userSessionRepository;
    private final JwtService jwtService;

    public SessionService(UserSessionRepository userSessionRepository, JwtService jwtService) {
        this.userSessionRepository = userSessionRepository;
        this.jwtService = jwtService;
    }

    public List<SessionView> getActiveSessions(Long userId, String authorizationHeader) {
        String currentRefreshTokenJti = extractCurrentRefreshTokenJti(authorizationHeader);
        LocalDateTime nowUtc = LocalDateTime.now(ZoneOffset.UTC);

        return userSessionRepository
                .findByUserIdAndIsRevokedFalseAndExpiresAtAfterOrderByLastActiveDesc(userId, nowUtc)
                .stream()
                .map(session -> new SessionView(
                        session.getId(),
                        session.getUserAgent(),
                        session.getIpAddress(),
                        session.getLastActive(),
                        session.getExpiresAt(),
                        currentRefreshTokenJti.equals(session.getRefreshTokenJti())
                ))
                .toList();
    }

    @Transactional
    public void revokeSession(Long userId, Long sessionId) {
        UserSession session = userSessionRepository.findByIdAndUserId(sessionId, userId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Session not found"));

        if (Boolean.TRUE.equals(session.getIsRevoked())) {
            return;
        }

        session.setIsRevoked(true);
        session.setLastActive(LocalDateTime.now(ZoneOffset.UTC));
        userSessionRepository.save(session);
    }

    @Transactional
    public int revokeAllSessionsExceptCurrent(Long userId, String authorizationHeader) {
        String currentRefreshTokenJti = extractCurrentRefreshTokenJti(authorizationHeader);
        LocalDateTime nowUtc = LocalDateTime.now(ZoneOffset.UTC);

        List<UserSession> sessions = userSessionRepository.findByUserIdAndIsRevokedFalse(userId);
        int revokedCount = 0;

        for (UserSession session : sessions) {
            if (!currentRefreshTokenJti.equals(session.getRefreshTokenJti())) {
                session.setIsRevoked(true);
                session.setLastActive(nowUtc);
                revokedCount++;
            }
        }

        if (revokedCount > 0) {
            userSessionRepository.saveAll(sessions);
        }

        return revokedCount;
    }

    private String extractCurrentRefreshTokenJti(String authorizationHeader) {
        String accessToken = extractBearerToken(authorizationHeader);
        if (accessToken == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Missing Authorization bearer token");
        }

        if (!jwtService.isTokenValid(accessToken, JwtService.TokenType.ACCESS)) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid or expired access token");
        }

        return jwtService.extractRefreshTokenJti(accessToken);
    }

    private String extractBearerToken(String authorizationHeader) {
        if (authorizationHeader == null || authorizationHeader.isBlank()) {
            return null;
        }

        String prefix = "Bearer ";
        if (!authorizationHeader.startsWith(prefix)) {
            return null;
        }

        String token = authorizationHeader.substring(prefix.length()).trim();
        return token.isBlank() ? null : token;
    }

    public record SessionView(
            Long sessionId,
            String userAgent,
            String ipAddress,
            LocalDateTime lastActive,
            LocalDateTime expiresAt,
            boolean current
    ) {
    }
}
