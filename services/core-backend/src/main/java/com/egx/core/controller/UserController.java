package com.egx.core.controller;

import com.egx.core.controller.dto.user.UpdateProfileRequest;
import com.egx.core.controller.dto.user.UserProfileResponse;
import com.egx.core.service.UserService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.Authentication;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping({"/users", "/api/core/users"})
@Validated
public class UserController {

    private final UserService userService;

    public UserController(UserService userService) {
        this.userService = userService;
    }

    @GetMapping("/me")
    public UserProfileResponse me(Authentication authentication) {
        Long userId = resolveUserId(authentication);
        UserService.UserProfile profile = userService.getProfile(userId);
        return mapProfile(profile);
    }

    @PutMapping("/me")
    public UserProfileResponse updateMe(
            Authentication authentication,
            @Valid @RequestBody UpdateProfileRequest request
    ) {
        Long userId = resolveUserId(authentication);
        UserService.UserProfile profile = userService.updateProfile(
                userId,
                new UserService.ProfileUpdateCommand(request.fullName(), request.phone())
        );
        return mapProfile(profile);
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

    private UserProfileResponse mapProfile(UserService.UserProfile profile) {
        return new UserProfileResponse(
                profile.userId(),
                profile.email(),
                profile.fullName(),
                profile.phone(),
                profile.tier().name(),
                profile.kycStatus().name(),
                profile.accountStatus().name(),
                profile.createdAt(),
                profile.updatedAt()
        );
    }
}
