package com.egx.core.security;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.util.WebUtils;

import java.io.IOException;

@Component
public class SecurityRateLimitingFilter extends OncePerRequestFilter {

    private final SecurityRateLimiterService rateLimiterService;
    private final JwtService jwtService;

    private final int authIpMaxRequests;
    private final long authIpWindowSeconds;
    private final int sessionMaxRequests;
    private final long sessionWindowSeconds;
    private final String accessTokenCookieName;

    public SecurityRateLimitingFilter(
            SecurityRateLimiterService rateLimiterService,
            JwtService jwtService,
            @Value("${app.security.rate-limit.auth-ip.max-requests:8}") int authIpMaxRequests,
            @Value("${app.security.rate-limit.auth-ip.window-seconds:300}") long authIpWindowSeconds,
            @Value("${app.security.rate-limit.session.max-requests:300}") int sessionMaxRequests,
            @Value("${app.security.rate-limit.session.window-seconds:60}") long sessionWindowSeconds,
            @Value("${app.security.cookies.access-token-name:egx_access_token}") String accessTokenCookieName
    ) {
        this.rateLimiterService = rateLimiterService;
        this.jwtService = jwtService;
        this.authIpMaxRequests = authIpMaxRequests;
        this.authIpWindowSeconds = authIpWindowSeconds;
        this.sessionMaxRequests = sessionMaxRequests;
        this.sessionWindowSeconds = sessionWindowSeconds;
        this.accessTokenCookieName = accessTokenCookieName;
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {
        String path = request.getServletPath();

        if (isAuthBruteForcePath(path)) {
            String clientIp = extractClientIp(request);
            SecurityRateLimiterService.RateLimitDecision decision = rateLimiterService.evaluate(
                    "auth-ip:" + clientIp,
                    authIpMaxRequests,
                    authIpWindowSeconds
            );

            applyHeaders(response, decision);
            if (!decision.allowed()) {
                rejectTooManyRequests(response, decision, "Too many authentication attempts");
                return;
            }
        } else {
            String sessionKey = resolveSessionRateLimitKey(request);
            if (sessionKey != null) {
                SecurityRateLimiterService.RateLimitDecision decision = rateLimiterService.evaluate(
                        "session:" + sessionKey,
                        sessionMaxRequests,
                        sessionWindowSeconds
                );

                applyHeaders(response, decision);
                if (!decision.allowed()) {
                    rejectTooManyRequests(response, decision, "Too many API requests for this session");
                    return;
                }
            }
        }

        filterChain.doFilter(request, response);
    }

    private boolean isAuthBruteForcePath(String path) {
        if (path == null) {
            return false;
        }

        return path.equals("/auth/login")
                || path.equals("/auth/register")
                || path.equals("/api/core/auth/login")
                || path.equals("/api/core/auth/register");
    }

    private String resolveSessionRateLimitKey(HttpServletRequest request) {
        String token = extractAccessToken(request);
        if (token == null || token.isBlank()) {
            return null;
        }

        try {
            if (!jwtService.isTokenValid(token, JwtService.TokenType.ACCESS)) {
                return null;
            }
            return jwtService.extractRefreshTokenJti(token);
        } catch (Exception ex) {
            return null;
        }
    }

    private String extractAccessToken(HttpServletRequest request) {
        String authorizationHeader = request.getHeader(HttpHeaders.AUTHORIZATION);
        if (authorizationHeader != null && authorizationHeader.startsWith("Bearer ")) {
            String token = authorizationHeader.substring(7).trim();
            if (!token.isBlank()) {
                return token;
            }
        }

        Cookie cookie = WebUtils.getCookie(request, accessTokenCookieName);
        if (cookie != null && cookie.getValue() != null && !cookie.getValue().isBlank()) {
            return cookie.getValue().trim();
        }

        return null;
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

    private void applyHeaders(
            HttpServletResponse response,
            SecurityRateLimiterService.RateLimitDecision decision
    ) {
        response.setHeader("X-RateLimit-Limit", String.valueOf(decision.limit()));
        response.setHeader("X-RateLimit-Remaining", String.valueOf(decision.remaining()));
        response.setHeader("X-RateLimit-Reset", String.valueOf(decision.resetEpochSecond()));
    }

    private void rejectTooManyRequests(
            HttpServletResponse response,
            SecurityRateLimiterService.RateLimitDecision decision,
            String message
    ) throws IOException {
        response.setStatus(HttpServletResponse.SC_TOO_MANY_REQUESTS);
        response.setHeader("Retry-After", String.valueOf(decision.retryAfterSeconds()));
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.getWriter().write("{\"error\":\"" + message + "\"}");
    }
}
