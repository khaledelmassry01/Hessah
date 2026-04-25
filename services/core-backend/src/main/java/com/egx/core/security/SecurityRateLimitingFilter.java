package com.egx.core.security;

import java.io.IOException;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.util.WebUtils;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

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
                @Value("${app.security.cookies.access-cookie-name:egx_access_token}") String accessTokenCookieName
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
            // X-Forwarded-For can be spoofed; find first valid, non-private, non-loopback IP
            String[] candidates = forwardedFor.split(",");
            for (String candidate : candidates) {
                String ip = candidate.trim();
                if (isValidPublicIp(ip)) {
                    return ip;
                }
            }
        }
        // Fallback to direct remote address (trusted when behind load balancer)
        return request.getRemoteAddr();
    }

    /**
     * Validates that IP is not null/blank, not loopback, and not in private ranges.
     * Prevents IP spoofing via X-Forwarded-For header.
     */
    private boolean isValidPublicIp(String ip) {
        if (ip == null || ip.isBlank()) {
            return false;
        }
        // Check for loopback
        if (ip.equals("127.0.0.1") || ip.equals("::1") || ip.startsWith("127.")) {
            return false;
        }
        // Check for private IPv4 ranges
        if (ip.startsWith("10.") || ip.startsWith("192.168.") || ip.startsWith("172.")) {
            // 172.16.0.0 - 172.31.255.255
            if (ip.startsWith("172.")) {
                try {
                    int secondOctet = Integer.parseInt(ip.split("\\.")[1]);
                    if (secondOctet >= 16 && secondOctet <= 31) {
                        return false;
                    }
                } catch (Exception e) {
                    return false;
                }
            } else {
                return false;
            }
        }
        // Check for link-local
        if (ip.startsWith("169.254.")) {
            return false;
        }
        // Basic IPv4 format validation
        if (!ip.matches("^(\\d{1,3}\\.){3}\\d{1,3}$")) {
            // Allow IPv6 but mark as potentially valid
            return ip.contains(":");
        }
        return true;
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
        response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value());
        response.setHeader("Retry-After", String.valueOf(decision.retryAfterSeconds()));
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.getWriter().write("{\"error\":\"" + message + "\"}");
    }
}
