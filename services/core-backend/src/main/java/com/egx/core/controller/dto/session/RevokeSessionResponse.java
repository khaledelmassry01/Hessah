package com.egx.core.controller.dto.session;

public record RevokeSessionResponse(
        Long sessionId,
        String message
) {
}
