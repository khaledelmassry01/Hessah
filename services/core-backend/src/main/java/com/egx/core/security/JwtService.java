package com.egx.core.security;

import com.egx.core.domain.enums.SubscriptionTier;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.Date;
import java.util.Locale;
import java.util.UUID;

@Service
public class JwtService {

    private static final String CLAIM_USER_ID = "userId";
    private static final String CLAIM_TIER = "tier";
    private static final String CLAIM_TOKEN_TYPE = "tokenType";
    private static final String CLAIM_REFRESH_TOKEN_JTI = "refreshTokenJti";

    private final SecretKey signingKey;
    private final Duration accessTokenTtl;
    private final Duration refreshTokenTtl;

    public JwtService(
            @Value("${app.security.jwt.secret}") String jwtSecret,
            @Value("${app.security.jwt.access-token-minutes:15}") long accessTokenMinutes,
            @Value("${app.security.jwt.refresh-token-days:7}") long refreshTokenDays
    ) {
        byte[] keyBytes = jwtSecret.getBytes(StandardCharsets.UTF_8);
        if (keyBytes.length < 32) {
            throw new IllegalStateException("JWT secret must be at least 32 bytes");
        }

        this.signingKey = Keys.hmacShaKeyFor(keyBytes);
        this.accessTokenTtl = Duration.ofMinutes(accessTokenMinutes);
        this.refreshTokenTtl = Duration.ofDays(refreshTokenDays);
    }

    public TokenPair issueTokenPair(Long userId, String subjectEmail, SubscriptionTier tier) {
        String refreshTokenJti = UUID.randomUUID().toString();
        String accessToken = generateAccessToken(userId, subjectEmail, tier, refreshTokenJti);
        String refreshToken = generateRefreshToken(userId, subjectEmail, tier, refreshTokenJti);

        return new TokenPair(
                accessToken,
                extractExpiration(accessToken),
                refreshToken,
                extractExpiration(refreshToken),
                refreshTokenJti
        );
    }

    public boolean isTokenValid(String token, TokenType tokenType) {
        try {
            Claims claims = parseClaims(token);
            String claimType = String.valueOf(claims.get(CLAIM_TOKEN_TYPE)).toUpperCase(Locale.ROOT);
            Date expiration = claims.getExpiration();
            return tokenType.name().equals(claimType)
                    && expiration != null
                    && expiration.toInstant().isAfter(Instant.now());
        } catch (JwtException | IllegalArgumentException ex) {
            return false;
        }
    }

    public Long extractUserId(String token) {
        Object value = parseClaims(token).get(CLAIM_USER_ID);
        if (value instanceof Number number) {
            return number.longValue();
        }
        if (value instanceof String stringValue) {
            return Long.valueOf(stringValue);
        }
        throw new IllegalArgumentException("Missing or invalid userId claim");
    }

    public SubscriptionTier extractTier(String token) {
        Object value = parseClaims(token).get(CLAIM_TIER);
        if (value == null) {
            throw new IllegalArgumentException("Missing tier claim");
        }
        return SubscriptionTier.valueOf(value.toString().toUpperCase(Locale.ROOT));
    }

    public String extractRefreshTokenJti(String token) {
        String claim = extractStringClaim(token, CLAIM_REFRESH_TOKEN_JTI);
        if (claim == null || claim.isBlank()) {
            throw new IllegalArgumentException("Missing refresh token JTI claim");
        }
        return claim;
    }

    public Instant extractExpiration(String token) {
        Date expiration = parseClaims(token).getExpiration();
        if (expiration == null) {
            throw new IllegalArgumentException("Token is missing expiration");
        }
        return expiration.toInstant();
    }

    private String extractStringClaim(String token, String claimName) {
        Object value = parseClaims(token).get(claimName);
        if (value == null) {
            return null;
        }
        return value.toString();
    }

    private String generateAccessToken(
            Long userId,
            String subjectEmail,
            SubscriptionTier tier,
            String refreshTokenJti
    ) {
        return generateToken(
                userId,
                subjectEmail,
                tier,
                TokenType.ACCESS,
                accessTokenTtl,
                UUID.randomUUID().toString(),
                refreshTokenJti
        );
    }

    private String generateRefreshToken(
            Long userId,
            String subjectEmail,
            SubscriptionTier tier,
            String refreshTokenJti
    ) {
        return generateToken(
                userId,
                subjectEmail,
                tier,
                TokenType.REFRESH,
                refreshTokenTtl,
                refreshTokenJti,
                refreshTokenJti
        );
    }

    private String generateToken(
            Long userId,
            String subjectEmail,
            SubscriptionTier tier,
            TokenType tokenType,
            Duration ttl,
            String tokenJti,
            String refreshTokenJti
    ) {
        Instant now = Instant.now();
        Instant expiry = now.plus(ttl);

        return Jwts.builder()
                .id(tokenJti)
                .subject(subjectEmail)
                .issuedAt(Date.from(now))
                .expiration(Date.from(expiry))
                .claim(CLAIM_USER_ID, userId)
                .claim(CLAIM_TIER, tier.name())
                .claim(CLAIM_TOKEN_TYPE, tokenType.name())
                .claim(CLAIM_REFRESH_TOKEN_JTI, refreshTokenJti)
                .signWith(signingKey)
                .compact();
    }

    private Claims parseClaims(String token) {
        return Jwts.parser()
                .verifyWith(signingKey)
                .build()
                .parseSignedClaims(token)
                .getPayload();
    }

    public enum TokenType {
        ACCESS,
        REFRESH
    }

    public record TokenPair(
            String accessToken,
            Instant accessTokenExpiresAt,
            String refreshToken,
            Instant refreshTokenExpiresAt,
            String refreshTokenJti
    ) {
    }
}
