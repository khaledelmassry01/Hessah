package com.egx.core.controller.dto.auth;

import java.time.Instant;

public record RefreshAccessTokenResponse(
        Long userId,
        String tier,
        String role,
        String accessToken,
        Instant accessTokenExpiresAt,
        String refreshToken,
        Instant refreshTokenExpiresAt
) {
}
