package com.egx.core.controller.dto.auth;

import jakarta.validation.constraints.NotBlank;

public record RefreshRequest(
        @NotBlank
        String refreshToken
) {
}
