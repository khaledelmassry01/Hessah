package com.egx.core.controller;

import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import com.egx.core.controller.dto.auth.AuthTokensResponse;
import com.egx.core.controller.dto.auth.LoginRequest;
import com.egx.core.controller.dto.auth.MessageResponse;
import com.egx.core.controller.dto.auth.RefreshAccessTokenResponse;
import com.egx.core.controller.dto.auth.RefreshRequest;
import com.egx.core.controller.dto.auth.RegisterRequest;
import com.egx.core.controller.dto.auth.RegisterResponse;
import com.egx.core.security.AuthCookieService;
import com.egx.core.service.AuthService;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;

@RestController
@RequestMapping("/auth")
@Validated
public class AuthController {

    private final AuthService authService;
        private final AuthCookieService authCookieService;

        public AuthController(AuthService authService, AuthCookieService authCookieService) {
        this.authService = authService;
                this.authCookieService = authCookieService;
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

        // Get primary role for backward compatibility (first role or USER)
        String primaryRole = registeredUser.roles().isEmpty() ? "USER" : registeredUser.roles().get(0);

        return new RegisterResponse(
                registeredUser.userId(),
                registeredUser.email(),
                registeredUser.fullName(),
                registeredUser.tier().name(),
                primaryRole,
                "User registered successfully"
        );
    }

    @PostMapping("/login")
    public AuthTokensResponse login(
            @Valid @RequestBody LoginRequest request,
            HttpServletRequest httpRequest,
            HttpServletResponse httpResponse
    ) {
        AuthService.AuthTokens tokens = authService.login(
                new AuthService.LoginCommand(
                        request.email(),
                        request.password(),
                        extractUserAgent(httpRequest),
                        extractClientIp(httpRequest)
                )
        );

        authCookieService.setAuthCookies(httpResponse, tokens.tokenPair());

        // Get primary role for backward compatibility (first role or USER)
        String primaryRole = tokens.roles().isEmpty() ? "USER" : tokens.roles().get(0);

        return new AuthTokensResponse(
                tokens.userId(),
                tokens.tier().name(),
                primaryRole,
                tokens.accessToken(),
                tokens.accessTokenExpiresAt(),
                tokens.refreshToken(),
                tokens.refreshTokenExpiresAt()
        );
    }

    @PostMapping("/refresh")
    public RefreshAccessTokenResponse refresh(
                        @RequestBody(required = false) RefreshRequest request,
                        HttpServletRequest httpRequest,
                        HttpServletResponse httpResponse
    ) {
                String refreshToken = request == null ? null : request.refreshToken();
                if (refreshToken == null || refreshToken.isBlank()) {
                        refreshToken = authCookieService.resolveRefreshToken(httpRequest);
                }

                if (refreshToken == null || refreshToken.isBlank()) {
                        throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Refresh token is required");
                }

        AuthService.AuthTokens tokens = authService.refresh(
                new AuthService.RefreshCommand(
                                                refreshToken,
                        extractUserAgent(httpRequest),
                        extractClientIp(httpRequest)
                )
        );

                authCookieService.setAuthCookies(httpResponse, tokens.tokenPair());

        // Get primary role for backward compatibility (first role or USER)
        String primaryRole = tokens.roles().isEmpty() ? "USER" : tokens.roles().get(0);

        return new RefreshAccessTokenResponse(
                tokens.userId(),
                tokens.tier().name(),
                primaryRole,
                tokens.accessToken(),
                tokens.accessTokenExpiresAt(),
                tokens.refreshToken(),
                tokens.refreshTokenExpiresAt()
        );
    }

    @PostMapping("/logout")
    public MessageResponse logout(
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false)
            String authorizationHeader,
            HttpServletRequest httpRequest,
            HttpServletResponse httpResponse
    ) {
        String accessToken = extractBearerToken(authorizationHeader);
        if (accessToken == null) {
            accessToken = authCookieService.resolveAccessToken(httpRequest);
        }

        authService.logout(accessToken);
        authCookieService.clearAuthCookies(httpResponse);
        return new MessageResponse("Logged out successfully");
    }

        private String extractBearerToken(String authorizationHeader) {
                if (authorizationHeader == null || authorizationHeader.isBlank()) {
                        return null;
                }

                String prefix = "Bearer ";
                if (!authorizationHeader.startsWith(prefix)) {
                        return null;
                }

                String token = authorizationHeader.substring(prefix.length()).trim();
                return token.isBlank() ? null : token;
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
