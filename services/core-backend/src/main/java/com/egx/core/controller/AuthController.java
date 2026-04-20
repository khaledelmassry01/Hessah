package com.egx.core.controller;

import com.egx.core.controller.dto.auth.AuthTokensResponse;
import com.egx.core.controller.dto.auth.LoginRequest;
import com.egx.core.controller.dto.auth.MessageResponse;
import com.egx.core.controller.dto.auth.RefreshAccessTokenResponse;
import com.egx.core.controller.dto.auth.RefreshRequest;
import com.egx.core.controller.dto.auth.RegisterRequest;
import com.egx.core.controller.dto.auth.RegisterResponse;
import com.egx.core.service.AuthService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.http.HttpHeaders;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/auth")
@Validated
public class AuthController {

    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @PostMapping("/register")
    public RegisterResponse register(@Valid @RequestBody RegisterRequest request) {
        AuthService.RegisteredUser registeredUser = authService.register(
                new AuthService.RegisterCommand(
                        request.email(),
                        request.password(),
                        request.fullName(),
                        request.phone()
                )
        );

        return new RegisterResponse(
                registeredUser.userId(),
                registeredUser.email(),
                registeredUser.fullName(),
                registeredUser.tier().name(),
                "User registered successfully"
        );
    }

    @PostMapping("/login")
    public AuthTokensResponse login(
            @Valid @RequestBody LoginRequest request,
            HttpServletRequest httpRequest
    ) {
        AuthService.AuthTokens tokens = authService.login(
                new AuthService.LoginCommand(
                        request.email(),
                        request.password(),
                        extractUserAgent(httpRequest),
                        extractClientIp(httpRequest)
                )
        );

        return new AuthTokensResponse(
                tokens.userId(),
                tokens.tier().name(),
                tokens.accessToken(),
                tokens.accessTokenExpiresAt(),
                tokens.refreshToken(),
                tokens.refreshTokenExpiresAt()
        );
    }

    @PostMapping("/refresh")
    public RefreshAccessTokenResponse refresh(
            @Valid @RequestBody RefreshRequest request,
            HttpServletRequest httpRequest
    ) {
        AuthService.AuthTokens tokens = authService.refresh(
                new AuthService.RefreshCommand(
                        request.refreshToken(),
                        extractUserAgent(httpRequest),
                        extractClientIp(httpRequest)
                )
        );

        return new RefreshAccessTokenResponse(
                tokens.userId(),
                tokens.tier().name(),
                tokens.accessToken(),
                tokens.accessTokenExpiresAt(),
                tokens.refreshToken(),
                tokens.refreshTokenExpiresAt()
        );
    }

    @PostMapping("/logout")
    public MessageResponse logout(
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false)
            String authorizationHeader
    ) {
        authService.logout(authorizationHeader);
        return new MessageResponse("Logged out successfully");
    }

        private String extractUserAgent(HttpServletRequest request) {
                String userAgent = request.getHeader(HttpHeaders.USER_AGENT);
                if (userAgent == null || userAgent.isBlank()) {
                        return "unknown";
                }
                return userAgent;
        }

        private String extractClientIp(HttpServletRequest request) {
                String forwardedFor = request.getHeader("X-Forwarded-For");
                if (forwardedFor != null && !forwardedFor.isBlank()) {
                        String[] candidates = forwardedFor.split(",");
                        if (candidates.length > 0 && !candidates[0].isBlank()) {
                                return candidates[0].trim();
                        }
                }
                return request.getRemoteAddr();
        }
}
