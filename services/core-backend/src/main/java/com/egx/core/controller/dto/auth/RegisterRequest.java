package com.egx.core.controller.dto.auth;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record RegisterRequest(
        @NotBlank
        @Email
        @Size(max = 255)
        String email,

        @NotBlank
        @Pattern(
                regexp = "^(?=.*[a-z])(?=.*[A-Z])(?=.*\\d)(?=.*[^A-Za-z\\d]).{8,72}$",
                message = "Password must be 8-72 chars and include upper, lower, digit, and special character"
        )
        String password,

        @NotBlank
        @Size(min = 2, max = 255)
        String fullName,

        @Size(max = 40)
        @Pattern(regexp = "^[0-9+()\\-\\s]*$", message = "Phone format is invalid")
        String phone
) {
}
