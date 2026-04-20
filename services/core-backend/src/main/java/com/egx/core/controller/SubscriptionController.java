package com.egx.core.controller;

import com.egx.core.domain.Subscription;
import com.egx.core.domain.enums.SubscriptionStatus;
import com.egx.core.domain.enums.SubscriptionTier;
import com.egx.core.repository.SubscriptionRepository;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.Authentication;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.Map;

@RestController
@Validated
public class SubscriptionController {

    private final SubscriptionRepository subscriptionRepository;

    public SubscriptionController(SubscriptionRepository subscriptionRepository) {
        this.subscriptionRepository = subscriptionRepository;
    }

    @PostMapping({
            "/subscriptions",
            "/api/core/subscriptions",
            "/subscriptions/activate",
            "/api/core/subscriptions/activate",
            "/users/{userId}/subscriptions",
            "/api/core/users/{userId}/subscriptions",
            "/users/{userId}/subscription",
            "/api/core/users/{userId}/subscription"
    })
    public SubscriptionActivationResponse activatePremium(
            Authentication authentication,
            @PathVariable(name = "userId", required = false) Long pathUserId,
            @RequestBody(required = false) Map<String, Object> payload
    ) {
        Long authenticatedUserId = resolveUserId(authentication);
        Long bodyUserId = extractLong(payload, "userId", "user_id");
        Long targetUserId = resolveTargetUserId(authenticatedUserId, pathUserId, bodyUserId);

        SubscriptionTier tier = parseTier(firstValue(payload, "tier"));
        SubscriptionStatus status = parseStatus(firstValue(payload, "status"));

        if (tier != SubscriptionTier.PREMIUM || status != SubscriptionStatus.ACTIVE) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "Only PREMIUM ACTIVE activation is supported by this endpoint"
            );
        }

        Subscription existing = subscriptionRepository
                .findFirstByUserIdAndTierAndStatusOrderByStartedAtDesc(
                        targetUserId,
                        SubscriptionTier.PREMIUM,
                        SubscriptionStatus.ACTIVE
                )
                .orElse(null);

        if (existing != null) {
            return new SubscriptionActivationResponse(
                    existing.getId(),
                    existing.getUserId(),
                    existing.getTier().name(),
                    existing.getStatus().name(),
                    existing.getStartedAt(),
                    "PREMIUM subscription already active"
            );
        }

        LocalDateTime nowUtc = LocalDateTime.now(ZoneOffset.UTC);

        Subscription subscription = new Subscription();
        subscription.setUserId(targetUserId);
        subscription.setTier(SubscriptionTier.PREMIUM);
        subscription.setStatus(SubscriptionStatus.ACTIVE);
        subscription.setStartedAt(nowUtc);
        subscription.setCreatedAt(nowUtc);
        subscription.setUpdatedAt(nowUtc);

        Subscription saved = subscriptionRepository.save(subscription);
        return new SubscriptionActivationResponse(
                saved.getId(),
                saved.getUserId(),
                saved.getTier().name(),
                saved.getStatus().name(),
                saved.getStartedAt(),
                "PREMIUM subscription activated"
        );
    }

    private SubscriptionTier parseTier(Object rawTier) {
        if (rawTier == null || rawTier.toString().isBlank()) {
            return SubscriptionTier.PREMIUM;
        }

        try {
            return SubscriptionTier.valueOf(rawTier.toString().trim().toUpperCase());
        } catch (IllegalArgumentException ex) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid tier value: " + rawTier);
        }
    }

    private SubscriptionStatus parseStatus(Object rawStatus) {
        if (rawStatus == null || rawStatus.toString().isBlank()) {
            return SubscriptionStatus.ACTIVE;
        }

        try {
            return SubscriptionStatus.valueOf(rawStatus.toString().trim().toUpperCase());
        } catch (IllegalArgumentException ex) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid status value: " + rawStatus);
        }
    }

    private Long resolveTargetUserId(Long authenticatedUserId, Long pathUserId, Long bodyUserId) {
        if (pathUserId != null && bodyUserId != null && !pathUserId.equals(bodyUserId)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Path userId does not match payload userId");
        }

        Long targetUserId = pathUserId != null ? pathUserId : bodyUserId;
        if (targetUserId == null) {
            targetUserId = authenticatedUserId;
        }

        if (!authenticatedUserId.equals(targetUserId)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Forbidden for requested user");
        }

        return targetUserId;
    }

    private Long extractLong(Map<String, Object> payload, String... keys) {
        BigDecimal value = toBigDecimal(firstValue(payload, keys));
        if (value == null) {
            return null;
        }
        return value.longValue();
    }

    private Object firstValue(Map<String, Object> payload, String... keys) {
        if (payload == null) {
            return null;
        }

        for (String key : keys) {
            if (payload.containsKey(key)) {
                return payload.get(key);
            }
        }

        return null;
    }

    private BigDecimal toBigDecimal(Object value) {
        if (value == null) {
            return null;
        }

        if (value instanceof BigDecimal decimalValue) {
            return decimalValue;
        }

        if (value instanceof Number numberValue) {
            return new BigDecimal(numberValue.toString());
        }

        if (value instanceof String stringValue) {
            String trimmed = stringValue.trim();
            if (trimmed.isEmpty()) {
                return null;
            }
            try {
                return new BigDecimal(trimmed);
            } catch (NumberFormatException ex) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid numeric value: " + stringValue);
            }
        }

        throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid numeric payload value type");
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

    public record SubscriptionActivationResponse(
            Long subscriptionId,
            Long userId,
            String tier,
            String status,
            LocalDateTime startedAt,
            String message
    ) {
    }
}
