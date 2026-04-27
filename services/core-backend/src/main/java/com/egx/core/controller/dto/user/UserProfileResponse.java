package com.egx.core.controller.dto.user;

import java.time.LocalDateTime;

public record UserProfileResponse(
        Long userId,
        String email,
        String fullName,
        String phone,
        String tier,
        String role,
        String kycStatus,
        String accountStatus,
        LocalDateTime createdAt,
        LocalDateTime updatedAt
) {
}
