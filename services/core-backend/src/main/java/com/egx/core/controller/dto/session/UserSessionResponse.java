package com.egx.core.controller.dto.session;

import java.time.LocalDateTime;

public record UserSessionResponse(
        Long sessionId,
        String userAgent,
        String ipAddress,
        LocalDateTime lastActive,
        LocalDateTime expiresAt,
        boolean current
) {
}
