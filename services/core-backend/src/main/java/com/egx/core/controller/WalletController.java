package com.egx.core.controller;

import com.egx.core.domain.Wallet;
import com.egx.core.service.WalletService;
import jakarta.validation.constraints.Positive;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.Authentication;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.util.Map;

@RestController
@RequestMapping({"/wallet", "/api/core/wallet", "/wallets", "/api/core/wallets"})
@Validated
public class WalletController {

    private final WalletService walletService;

    public WalletController(WalletService walletService) {
        this.walletService = walletService;
    }

    @GetMapping("/{userId}")
    public WalletResponse getWalletByPath(
            Authentication authentication,
            @PathVariable @Positive Long userId
    ) {
        Long authenticatedUserId = resolveUserId(authentication);
        assertOwnership(authenticatedUserId, userId);

        return mapWallet(walletService.getWalletByUserId(userId));
    }

    @GetMapping(params = "userId")
    public WalletResponse getWalletByQuery(
            Authentication authentication,
            @RequestParam("userId") @Positive Long userId
    ) {
        Long authenticatedUserId = resolveUserId(authentication);
        assertOwnership(authenticatedUserId, userId);

        return mapWallet(walletService.getWalletByUserId(userId));
    }

    @PostMapping({"/fund", "/{userId}/fund", "/{userId}/deposit"})
    public WalletFundResponse fundWalletPost(
            Authentication authentication,
            @PathVariable(name = "userId", required = false) Long pathUserId,
            @RequestBody(required = false) Map<String, Object> payload
    ) {
        return fundWallet(authentication, pathUserId, payload);
    }

    @PutMapping({"/fund", "/{userId}/fund", "/{userId}/deposit"})
    public WalletFundResponse fundWalletPut(
            Authentication authentication,
            @PathVariable(name = "userId", required = false) Long pathUserId,
            @RequestBody(required = false) Map<String, Object> payload
    ) {
        return fundWallet(authentication, pathUserId, payload);
    }

    private WalletFundResponse fundWallet(
            Authentication authentication,
            Long pathUserId,
            Map<String, Object> payload
    ) {
        Long authenticatedUserId = resolveUserId(authentication);
        Long bodyUserId = extractLong(payload, "userId", "user_id");
        Long targetUserId = resolveTargetUserId(authenticatedUserId, pathUserId, bodyUserId);
        BigDecimal amountEgp = extractAmount(payload);

        Wallet wallet = walletService.fundWallet(targetUserId, amountEgp);
        WalletResponse walletResponse = mapWallet(wallet);

        return new WalletFundResponse(
                walletResponse.walletId(),
                walletResponse.userId(),
                walletResponse.currency(),
                walletResponse.availableBalance(),
                walletResponse.lockedBalance(),
                amountEgp,
                "Wallet funded successfully"
        );
    }

    private Long resolveTargetUserId(Long authenticatedUserId, Long pathUserId, Long bodyUserId) {
        if (pathUserId != null && bodyUserId != null && !pathUserId.equals(bodyUserId)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Path userId does not match payload userId");
        }

        Long targetUserId = pathUserId != null ? pathUserId : bodyUserId;
        if (targetUserId == null) {
            targetUserId = authenticatedUserId;
        }

        assertOwnership(authenticatedUserId, targetUserId);
        return targetUserId;
    }

    private void assertOwnership(Long authenticatedUserId, Long targetUserId) {
        if (!authenticatedUserId.equals(targetUserId)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Forbidden for requested user");
        }
    }

    private BigDecimal extractAmount(Map<String, Object> payload) {
        BigDecimal amount = toBigDecimal(
                firstValue(payload, "amountEgp", "amount_egp", "amount")
        );

        if (amount == null || amount.compareTo(BigDecimal.ZERO) <= 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "amountEgp must be greater than zero");
        }

        return amount;
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

    private Long extractLong(Map<String, Object> payload, String... keys) {
        BigDecimal value = toBigDecimal(firstValue(payload, keys));
        if (value == null) {
            return null;
        }
        return value.longValue();
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

    private WalletResponse mapWallet(Wallet wallet) {
        return new WalletResponse(
                wallet.getId(),
                wallet.getUserId(),
                wallet.getCurrency(),
                wallet.getAvailableBalance(),
                wallet.getLockedBalance(),
                wallet.getUpdatedAt()
        );
    }

    public record WalletResponse(
            Long walletId,
            Long userId,
            String currency,
            BigDecimal availableBalance,
            BigDecimal lockedBalance,
            java.time.LocalDateTime updatedAt
    ) {
    }

    public record WalletFundResponse(
            Long walletId,
            Long userId,
            String currency,
            BigDecimal availableBalance,
            BigDecimal lockedBalance,
            BigDecimal amountEgp,
            String message
    ) {
    }
}
