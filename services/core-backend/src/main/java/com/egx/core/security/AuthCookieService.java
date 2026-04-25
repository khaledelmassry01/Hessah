package com.egx.core.security;

import java.time.Duration;
import java.time.Instant;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.Service;

import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

@Service
public class AuthCookieService {

    // P2 Fix: SameSite=Strict prevents CSRF attacks by only sending cookies on same-site requests
    private static final String SAME_SITE_STRICT = "Strict";

    private final boolean secureCookies;
    private final String accessCookieName;
    private final String refreshCookieName;

    public AuthCookieService(
            @Value("${app.security.cookies.secure:true}") boolean secureCookies,
            @Value("${app.security.cookies.access-cookie-name:egx_access_token}") String accessCookieName,
            @Value("${app.security.cookies.refresh-cookie-name:egx_refresh_token}") String refreshCookieName
    ) {
        this.secureCookies = secureCookies;
        this.accessCookieName = accessCookieName;
        this.refreshCookieName = refreshCookieName;
    }

    public void setAuthCookies(HttpServletResponse response, JwtService.TokenPair tokenPair) {
        response.addHeader(
                HttpHeaders.SET_COOKIE,
                buildTokenCookie(
                        accessCookieName,
                        tokenPair.accessToken(),
                        maxAgeUntil(tokenPair.accessTokenExpiresAt())
                ).toString()
        );

        response.addHeader(
                HttpHeaders.SET_COOKIE,
                buildTokenCookie(
                        refreshCookieName,
                        tokenPair.refreshToken(),
                        maxAgeUntil(tokenPair.refreshTokenExpiresAt())
                ).toString()
        );
    }

    public void clearAuthCookies(HttpServletResponse response) {
        response.addHeader(
                HttpHeaders.SET_COOKIE,
                buildTokenCookie(accessCookieName, "", Duration.ZERO).toString()
        );

        response.addHeader(
                HttpHeaders.SET_COOKIE,
                buildTokenCookie(refreshCookieName, "", Duration.ZERO).toString()
        );
    }

    public String resolveAccessToken(HttpServletRequest request) {
        return readCookieValue(request, accessCookieName);
    }

    public String resolveRefreshToken(HttpServletRequest request) {
        return readCookieValue(request, refreshCookieName);
    }

    private ResponseCookie buildTokenCookie(String cookieName, String value, Duration maxAge) {
        return ResponseCookie.from(cookieName, value)
                .httpOnly(true)          // P2 Fix: Prevent XSS via JavaScript access
                .secure(secureCookies)   // P2 Fix: Only transmit over HTTPS in production
                .sameSite(SAME_SITE_STRICT) // P2 Fix: Strict CSRF protection
                .path("/")
                .maxAge(maxAge)
                .build();
    }

    private Duration maxAgeUntil(Instant expiry) {
        Duration remaining = Duration.between(Instant.now(), expiry);
        return remaining.isNegative() ? Duration.ZERO : remaining;
    }

    private String readCookieValue(HttpServletRequest request, String cookieName) {
        Cookie[] cookies = request.getCookies();
        if (cookies == null || cookies.length == 0) {
            return null;
        }

        for (Cookie cookie : cookies) {
            if (cookieName.equals(cookie.getName())) {
                String value = cookie.getValue();
                if (value == null || value.isBlank()) {
                    return null;
                }
                return value.trim();
            }
        }

        return null;
    }
}
