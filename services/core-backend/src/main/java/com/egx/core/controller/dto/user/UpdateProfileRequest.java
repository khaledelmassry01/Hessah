package com.egx.core.controller.dto.user;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record UpdateProfileRequest(
        @NotBlank
        @Size(min = 2, max = 255)
        String fullName,

        @Size(max = 40)
        @Pattern(regexp = "^[0-9+()\\-\\s]*$", message = "Phone format is invalid")
        String phone
) {
}
