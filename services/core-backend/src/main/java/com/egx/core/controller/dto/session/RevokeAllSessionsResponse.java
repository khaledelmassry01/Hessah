package com.egx.core.controller.dto.session;

public record RevokeAllSessionsResponse(
        int revokedCount,
        String message
) {
}
