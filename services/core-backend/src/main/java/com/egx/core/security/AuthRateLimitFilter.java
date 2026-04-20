package com.egx.core.security;

import io.github.bucket4j.Bandwidth;
import io.github.bucket4j.Bucket;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.time.Duration;
import java.util.Locale;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

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
            String[] candidates = forwardedFor.split(",");
            if (candidates.length > 0 && !candidates[0].isBlank()) {
                return candidates[0].trim();
            }
        }
        return request.getRemoteAddr();
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
