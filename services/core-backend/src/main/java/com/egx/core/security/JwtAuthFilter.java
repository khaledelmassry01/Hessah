package com.egx.core.security;

import java.io.IOException;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.List;

import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.authentication.WebAuthenticationDetailsSource;
import org.springframework.web.filter.OncePerRequestFilter;

import com.egx.core.domain.User;
import com.egx.core.domain.enums.AccountStatus;
import com.egx.core.domain.enums.SubscriptionTier;
import com.egx.core.repository.TokenBlacklistRepository;
import com.egx.core.repository.UserRepository;
import com.egx.core.repository.UserSessionRepository;

import io.jsonwebtoken.JwtException;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

public class JwtAuthFilter extends OncePerRequestFilter {

    private final JwtService jwtService;
    private final TokenBlacklistRepository tokenBlacklistRepository;
    private final UserRepository userRepository;
    private final UserSessionRepository userSessionRepository;
    private final AuthCookieService authCookieService;

    public JwtAuthFilter(
            JwtService jwtService,
            TokenBlacklistRepository tokenBlacklistRepository,
            UserRepository userRepository,
            UserSessionRepository userSessionRepository,
            AuthCookieService authCookieService
    ) {
        this.jwtService = jwtService;
        this.tokenBlacklistRepository = tokenBlacklistRepository;
        this.userRepository = userRepository;
        this.userSessionRepository = userSessionRepository;
        this.authCookieService = authCookieService;
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {
        String path = request.getServletPath();

        if (isPublicPath(path)) {
            filterChain.doFilter(request, response);
            return;
        }

        String authorizationHeader = request.getHeader(HttpHeaders.AUTHORIZATION);
        String token = extractBearerToken(authorizationHeader);
        if (token == null) {
            token = authCookieService.resolveAccessToken(request);
        }

        if (token == null) {
            filterChain.doFilter(request, response);
            return;
        }

        if (token.isBlank()) {
            rejectUnauthorized(response, "Missing bearer token");
            return;
        }

        if (tokenBlacklistRepository.existsByToken(token)) {
            rejectUnauthorized(response, "Token has been revoked");
            return;
        }

        try {
            if (!jwtService.isTokenValid(token, JwtService.TokenType.ACCESS)) {
                rejectUnauthorized(response, "Invalid or expired access token");
                return;
            }

            Long userId = jwtService.extractUserId(token);
            User user = userRepository.findById(userId).orElse(null);
            if (user == null || user.getAccountStatus() != AccountStatus.ACTIVE) {
                rejectUnauthorized(response, "User account is not active");
                return;
            }

                String refreshTokenJti = jwtService.extractRefreshTokenJti(token);
                boolean activeSession = userSessionRepository
                    .existsByUserIdAndRefreshTokenJtiAndIsRevokedFalseAndExpiresAtAfter(
                        userId,
                        refreshTokenJti,
                        LocalDateTime.now(ZoneOffset.UTC)
                    );
                if (!activeSession) {
                rejectUnauthorized(response, "Session revoked or expired");
                return;
                }

            SubscriptionTier tier = jwtService.extractTier(token);
            UsernamePasswordAuthenticationToken authentication = new UsernamePasswordAuthenticationToken(
                    userId,
                    null,
                    List.of(new SimpleGrantedAuthority("ROLE_" + tier.name()))
            );
            authentication.setDetails(new WebAuthenticationDetailsSource().buildDetails(request));
            SecurityContextHolder.getContext().setAuthentication(authentication);
        } catch (JwtException | IllegalArgumentException ex) {
            SecurityContextHolder.clearContext();
            rejectUnauthorized(response, "Invalid JWT");
            return;
        }

        filterChain.doFilter(request, response);
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

    private boolean isPublicPath(String path) {
        if (path == null || path.isBlank()) {
            return false;
        }

        return path.equals("/error")
                || path.equals("/actuator/health")
                || path.equals("/actuator/info")
                || path.equals("/instruments/bulk")
                || path.equals("/api/core/instruments/bulk")
                || path.equals("/instruments")
                || path.equals("/instruments/catalog")
                || path.equals("/instruments/ids")
                || path.equals("/api/core/instruments")
                || path.equals("/api/core/instruments/catalog")
                || path.equals("/api/core/instruments/ids")
                || path.equals("/market-data/bulk")
                || path.equals("/api/core/market-data/bulk")
                || path.startsWith("/model-performance/")
                || path.startsWith("/api/core/model-performance/")
                || path.equals("/auth")
                || path.startsWith("/auth/")
                || path.equals("/api/core/auth")
                || path.startsWith("/api/core/auth/")
                || path.startsWith("/swagger-ui/")
                || path.startsWith("/v3/api-docs");
    }

    private void rejectUnauthorized(HttpServletResponse response, String message) throws IOException {
        response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.getWriter().write("{\"error\":\"" + message + "\"}");
    }
}
