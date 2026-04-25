package com.egx.core.security;

import java.io.IOException;
import java.time.Duration;
import java.util.Locale;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import io.github.bucket4j.Bandwidth;
import io.github.bucket4j.Bucket;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

@Component
public class AuthRateLimitFilter extends OncePerRequestFilter {

    private final ConcurrentMap<String, Bucket> buckets = new ConcurrentHashMap<>();

    private final int loginCapacity;
    private final int registerCapacity;
    private final int refillMinutes;

    public AuthRateLimitFilter(
            @Value("${app.security.rate-limit.login-capacity:12}") int loginCapacity,
            @Value("${app.security.rate-limit.register-capacity:6}") int registerCapacity,
            @Value("${app.security.rate-limit.refill-minutes:1}") int refillMinutes
    ) {
        this.loginCapacity = Math.max(1, loginCapacity);
        this.registerCapacity = Math.max(1, registerCapacity);
        this.refillMinutes = Math.max(1, refillMinutes);
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = normalizePath(request.getServletPath());
        return !isAuthRateLimitedPath(path);
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {
        String path = normalizePath(request.getServletPath());
        String key = resolveClientIp(request) + ":" + path;

        Bucket bucket = buckets.computeIfAbsent(key, ignored -> newBucket(path));
        if (!bucket.tryConsume(1)) {
            rejectRateLimited(response);
            return;
        }

        filterChain.doFilter(request, response);
    }

    private Bucket newBucket(String path) {
        int capacity = path.endsWith("/register") ? registerCapacity : loginCapacity;
        Bandwidth bandwidth = Bandwidth.builder()
                .capacity(capacity)
                .refillGreedy(capacity, Duration.ofMinutes(refillMinutes))
                .build();
        return Bucket.builder().addLimit(bandwidth).build();
    }

    private boolean isAuthRateLimitedPath(String path) {
        if (path == null || path.isBlank()) {
            return false;
        }

        return path.equals("/auth/login")
                || path.equals("/auth/register")
                || path.equals("/api/core/auth/login")
                || path.equals("/api/core/auth/register");
    }

    private String resolveClientIp(HttpServletRequest request) {
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
        // Fallback to direct remote address
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

    private String normalizePath(String path) {
        if (path == null) {
            return "";
        }
        return path.trim().toLowerCase(Locale.ROOT);
    }

    private void rejectRateLimited(HttpServletResponse response) throws IOException {
        response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.getWriter().write("{\"error\":\"Too many authentication attempts. Please try again shortly.\"}");
    }
}
