package com.egx.core.controller;

import com.egx.core.controller.dto.session.RevokeAllSessionsResponse;
import com.egx.core.controller.dto.session.RevokeSessionResponse;
import com.egx.core.controller.dto.session.UserSessionResponse;
import com.egx.core.service.SessionService;
import jakarta.validation.constraints.Positive;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.Authentication;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;

@RestController
@RequestMapping({"/users/me/sessions", "/api/core/users/me/sessions"})
@Validated
public class SessionController {

    private final SessionService sessionService;

    public SessionController(SessionService sessionService) {
        this.sessionService = sessionService;
    }

    @GetMapping
    public List<UserSessionResponse> listSessions(
            Authentication authentication,
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false)
            String authorizationHeader
    ) {
        Long userId = resolveUserId(authentication);

        return sessionService.getActiveSessions(userId, authorizationHeader)
                .stream()
                .map(this::mapSession)
                .toList();
    }

    @DeleteMapping("/{sessionId}")
    public RevokeSessionResponse revokeSession(
            Authentication authentication,
            @PathVariable @Positive Long sessionId
    ) {
        Long userId = resolveUserId(authentication);
        sessionService.revokeSession(userId, sessionId);

        return new RevokeSessionResponse(sessionId, "Session revoked successfully");
    }

    @DeleteMapping
    public RevokeAllSessionsResponse revokeAllSessionsExceptCurrent(
            Authentication authentication,
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false)
            String authorizationHeader
    ) {
        Long userId = resolveUserId(authentication);
        int revokedCount = sessionService.revokeAllSessionsExceptCurrent(userId, authorizationHeader);

        return new RevokeAllSessionsResponse(revokedCount, "Other sessions revoked successfully");
    }

    private Long resolveUserId(Authentication authentication) {
        if (authentication == null || !authentication.isAuthenticated()) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Authentication is required");
        }

        Object principal = authentication.getPrincipal();
        if (principal instanceof Number number) {
            return number.longValue();
        }

        throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Unable to resolve authenticated user");
    }

    private UserSessionResponse mapSession(SessionService.SessionView session) {
        return new UserSessionResponse(
                session.sessionId(),
                session.userAgent(),
                session.ipAddress(),
                session.lastActive(),
                session.expiresAt(),
                session.current()
        );
    }
}
