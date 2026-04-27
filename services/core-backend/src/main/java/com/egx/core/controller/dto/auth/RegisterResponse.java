package com.egx.core.controller.dto.auth;

public record RegisterResponse(
        Long userId,
        String email,
        String fullName,
        String tier,
        String role,
        String message
) {
}
