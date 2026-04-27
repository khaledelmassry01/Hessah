package com.egx.core.service;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;

import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import com.egx.core.domain.Role;
import com.egx.core.domain.Subscription;
import com.egx.core.domain.TokenBlacklist;
import com.egx.core.domain.User;
import com.egx.core.domain.UserSession;
import com.egx.core.domain.Wallet;
import com.egx.core.domain.enums.AccountStatus;
import com.egx.core.domain.enums.KycStatus;
import com.egx.core.domain.enums.SubscriptionStatus;
import com.egx.core.domain.enums.SubscriptionTier;
import com.egx.core.repository.RoleRepository;
import com.egx.core.repository.SubscriptionRepository;
import com.egx.core.repository.TokenBlacklistRepository;
import com.egx.core.repository.UserRepository;
import com.egx.core.repository.UserSessionRepository;
import com.egx.core.repository.WalletRepository;
import com.egx.core.security.JwtService;

import jakarta.transaction.Transactional;

@Service
public class AuthService {

    private final UserRepository userRepository;
    private final SubscriptionRepository subscriptionRepository;
    private final WalletRepository walletRepository;
    private final TokenBlacklistRepository tokenBlacklistRepository;
    private final UserSessionRepository userSessionRepository;
    private final RoleRepository roleRepository;
    private final PasswordEncoder passwordEncoder;
    private final JwtService jwtService;
    private final SecurityAuditService securityAuditService;

    public AuthService(
            UserRepository userRepository,
            SubscriptionRepository subscriptionRepository,
            WalletRepository walletRepository,
            TokenBlacklistRepository tokenBlacklistRepository,
            UserSessionRepository userSessionRepository,
            RoleRepository roleRepository,
            PasswordEncoder passwordEncoder,
            JwtService jwtService,
            SecurityAuditService securityAuditService
    ) {
        this.userRepository = userRepository;
        this.subscriptionRepository = subscriptionRepository;
        this.walletRepository = walletRepository;
        this.tokenBlacklistRepository = tokenBlacklistRepository;
        this.userSessionRepository = userSessionRepository;
        this.roleRepository = roleRepository;
        this.passwordEncoder = passwordEncoder;
        this.jwtService = jwtService;
        this.securityAuditService = securityAuditService;
    }

    @Transactional
    public RegisteredUser register(RegisterCommand command) {
        String normalizedEmail = normalizeEmail(command.email());
        userRepository.findByEmail(normalizedEmail).ifPresent(existing -> {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Email is already registered");
        });

        LocalDateTime now = LocalDateTime.now(ZoneOffset.UTC);

        User user = new User();
        user.setPublicUuid(UUID.randomUUID().toString());
        user.setEmail(normalizedEmail);
        user.setPasswordHash(passwordEncoder.encode(command.password()));
        user.setFullName(command.fullName().trim());
        user.setPhone(normalizePhone(command.phone()));
        user.setKycStatus(KycStatus.PENDING);
        user.setAccountStatus(AccountStatus.ACTIVE);
        user.setCreatedAt(now);
        user.setUpdatedAt(now);

        // Assign default USER role from many-to-many RBAC
        Role defaultRole = roleRepository.findByName("USER")
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "Default role not found"));
        user.addRole(defaultRole);

        User savedUser = userRepository.save(user);

        Subscription subscription = new Subscription();
        subscription.setUserId(savedUser.getId());
        subscription.setTier(SubscriptionTier.FREE);
        subscription.setStatus(SubscriptionStatus.ACTIVE);
        subscription.setStartedAt(now);
        subscription.setCreatedAt(now);
        subscription.setUpdatedAt(now);
        subscriptionRepository.save(subscription);

        Wallet wallet = new Wallet();
        wallet.setUserId(savedUser.getId());
        wallet.setCurrency("EGP");
        wallet.setAvailableBalance(BigDecimal.ZERO.setScale(4));
        wallet.setLockedBalance(BigDecimal.ZERO.setScale(4));
        wallet.setVersion(0L);
        wallet.setCreatedAt(now);
        wallet.setUpdatedAt(now);
        walletRepository.save(wallet);

        // Convert roles to list of role names for response
        List<String> roleNames = savedUser.getRoles().stream()
                .map(Role::getName)
                .collect(Collectors.toList());

        return new RegisteredUser(
                savedUser.getId(),
                savedUser.getEmail(),
                savedUser.getFullName(),
                SubscriptionTier.FREE,
                roleNames
        );
    }

    @Transactional
    public AuthTokens login(LoginCommand command) {
        String normalizedEmail = normalizeEmail(command.email());
        User user = userRepository.findByEmail(normalizedEmail).orElse(null);

        if (user == null) {
            securityAuditService.log(
                "LOGIN",
                null,
                "FAILED",
                buildAuditDetails(
                    "INVALID_CREDENTIALS",
                    command.ipAddress(),
                    Map.of("email", normalizedEmail)
                )
            );
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid email or password");
        }

        if (!passwordEncoder.matches(command.password(), user.getPasswordHash())) {
            securityAuditService.log(
                "LOGIN",
                user.getId(),
                "FAILED",
                buildAuditDetails("INVALID_CREDENTIALS", command.ipAddress(), null)
            );
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid email or password");
        }

        if (user.getAccountStatus() != AccountStatus.ACTIVE) {
            securityAuditService.log(
                "LOGIN",
                user.getId(),
                "FAILED",
                buildAuditDetails("ACCOUNT_INACTIVE", command.ipAddress(), null)
            );
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Account is not active");
        }

        SubscriptionTier tier = resolveCurrentTier(user.getId());
        // Get all roles as comma-separated string for JWT
        String rolesCsv = user.getRoles().stream()
                .map(Role::getName)
                .collect(Collectors.joining(","));
        JwtService.TokenPair tokenPair = jwtService.issueTokenPair(user.getId(), user.getEmail(), tier, rolesCsv);
        LocalDateTime nowUtc = LocalDateTime.now(ZoneOffset.UTC);

        UserSession session = new UserSession();
        session.setUserId(user.getId());
        session.setRefreshTokenJti(tokenPair.refreshTokenJti());
        session.setUserAgent(sanitizeUserAgent(command.userAgent()));
        session.setIpAddress(normalizeIp(command.ipAddress()));
        session.setLastActive(nowUtc);
        session.setExpiresAt(LocalDateTime.ofInstant(tokenPair.refreshTokenExpiresAt(), ZoneOffset.UTC));
        session.setIsRevoked(false);
        userSessionRepository.save(session);

        securityAuditService.log(
            "LOGIN",
            user.getId(),
            "SUCCESS",
            buildAuditDetails(
                "OK",
                command.ipAddress(),
                Map.of("tier", tier.name(), "role", user.getPrimaryRoleName())
            )
        );

        // Convert roles to list for response
        List<String> roleNames = user.getRoles().stream()
                .map(Role::getName)
                .collect(Collectors.toList());

        return new AuthTokens(
                user.getId(),
                tier,
                roleNames,
                tokenPair.accessToken(),
                tokenPair.accessTokenExpiresAt(),
                tokenPair.refreshToken(),
                tokenPair.refreshTokenExpiresAt(),
                tokenPair
        );
    }

    @Transactional
    public AuthTokens refresh(RefreshCommand command) {
        String refreshToken = command.refreshToken();
        if (refreshToken == null || refreshToken.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Refresh token is required");
        }

        if (tokenBlacklistRepository.existsByToken(refreshToken)) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Refresh token is revoked");
        }

        if (!jwtService.isTokenValid(refreshToken, JwtService.TokenType.REFRESH)) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid or expired refresh token");
        }

        Long userId = jwtService.extractUserId(refreshToken);
        String refreshTokenJti = jwtService.extractRefreshTokenJti(refreshToken);
        LocalDateTime nowUtc = LocalDateTime.now(ZoneOffset.UTC);

        UserSession existingSession = userSessionRepository
            .findFirstByUserIdAndRefreshTokenJtiAndIsRevokedFalseAndExpiresAtAfter(
                userId,
                refreshTokenJti,
                nowUtc
            )
            .orElseThrow(() -> new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Refresh session is revoked or expired"));

        User user = userRepository.findById(userId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.UNAUTHORIZED, "User not found"));

        if (user.getAccountStatus() != AccountStatus.ACTIVE) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Account is not active");
        }

        blacklistToken(refreshToken, jwtService.extractExpiration(refreshToken), nowUtc);

        SubscriptionTier tier = resolveCurrentTier(user.getId());
        // Get all roles as comma-separated string for JWT
        String rolesCsv = user.getRoles().stream()
                .map(Role::getName)
                .collect(Collectors.joining(","));
        JwtService.TokenPair tokenPair = jwtService.issueTokenPair(user.getId(), user.getEmail(), tier, rolesCsv);

        existingSession.setRefreshTokenJti(tokenPair.refreshTokenJti());
        if (command.userAgent() != null && !command.userAgent().isBlank()) {
            existingSession.setUserAgent(sanitizeUserAgent(command.userAgent()));
        }
        if (command.ipAddress() != null && !command.ipAddress().isBlank()) {
            existingSession.setIpAddress(normalizeIp(command.ipAddress()));
        }
        existingSession.setLastActive(nowUtc);
        existingSession.setExpiresAt(LocalDateTime.ofInstant(tokenPair.refreshTokenExpiresAt(), ZoneOffset.UTC));
        existingSession.setIsRevoked(false);
        userSessionRepository.save(existingSession);

        // Convert roles to list for response
        List<String> roleNames = user.getRoles().stream()
                .map(Role::getName)
                .collect(Collectors.toList());

        return new AuthTokens(
                user.getId(),
                tier,
                roleNames,
                tokenPair.accessToken(),
                tokenPair.accessTokenExpiresAt(),
                tokenPair.refreshToken(),
                tokenPair.refreshTokenExpiresAt(),
                tokenPair
        );
    }

    @Transactional
    public void logout(String accessToken) {
        if (accessToken == null || accessToken.isBlank()) {
            return;
        }

        if (!jwtService.isTokenValid(accessToken, JwtService.TokenType.ACCESS)) {
            return;
        }

        LocalDateTime nowUtc = LocalDateTime.now(ZoneOffset.UTC);
        blacklistToken(accessToken, jwtService.extractExpiration(accessToken), nowUtc);

        Long userId = jwtService.extractUserId(accessToken);
        String refreshTokenJti = jwtService.extractRefreshTokenJti(accessToken);
        userSessionRepository
                .findFirstByUserIdAndRefreshTokenJtiAndIsRevokedFalseAndExpiresAtAfter(
                        userId,
                        refreshTokenJti,
                        nowUtc
                )
                .ifPresent(session -> {
                    session.setIsRevoked(true);
                    session.setLastActive(nowUtc);
                    userSessionRepository.save(session);
                });
    }

    private void blacklistToken(String token, Instant expiresAt, LocalDateTime nowUtc) {
        if (tokenBlacklistRepository.existsByToken(token)) {
            return;
        }

        TokenBlacklist blacklist = new TokenBlacklist();
        blacklist.setToken(token);
        blacklist.setExpiresAt(LocalDateTime.ofInstant(expiresAt, ZoneOffset.UTC));
        blacklist.setCreatedAt(nowUtc);
        tokenBlacklistRepository.save(blacklist);
    }

    private SubscriptionTier resolveCurrentTier(Long userId) {
        return subscriptionRepository
                .findFirstByUserIdAndTierAndStatusOrderByStartedAtDesc(
                        userId,
                        SubscriptionTier.PREMIUM,
                        SubscriptionStatus.ACTIVE
                )
                .map(Subscription::getTier)
                .orElse(SubscriptionTier.FREE);
    }

    private String normalizeEmail(String email) {
        return email.trim().toLowerCase(Locale.ROOT);
    }

    private String normalizePhone(String phone) {
        if (phone == null || phone.isBlank()) {
            return null;
        }
        return phone.trim();
    }

    private String sanitizeUserAgent(String userAgent) {
        if (userAgent == null || userAgent.isBlank()) {
            return "unknown";
        }
        String normalized = userAgent.trim();
        return normalized.length() > 512 ? normalized.substring(0, 512) : normalized;
    }

    private String normalizeIp(String ipAddress) {
        if (ipAddress == null || ipAddress.isBlank()) {
            return null;
        }
        String normalized = ipAddress.trim();
        return normalized.length() > 64 ? normalized.substring(0, 64) : normalized;
    }

    private Map<String, Object> buildAuditDetails(String reason, String ipAddress, Map<String, Object> extras) {
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("reason", reason);

        String normalizedIp = normalizeIp(ipAddress);
        if (normalizedIp != null) {
            details.put("ip", normalizedIp);
        }

        if (extras != null && !extras.isEmpty()) {
            details.putAll(extras);
        }

        return details;
    }

    public record RegisterCommand(String email, String password, String fullName, String phone) {
    }

    public record LoginCommand(String email, String password, String userAgent, String ipAddress) {
    }

    public record RefreshCommand(String refreshToken, String userAgent, String ipAddress) {
    }

    public record RegisteredUser(Long userId, String email, String fullName, SubscriptionTier tier, List<String> roles) {
    }

    public record AuthTokens(
            Long userId,
            SubscriptionTier tier,
            List<String> roles,
            String accessToken,
            Instant accessTokenExpiresAt,
            String refreshToken,
            Instant refreshTokenExpiresAt,
            JwtService.TokenPair tokenPair
    ) {
    }
}
