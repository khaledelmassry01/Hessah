package com.egx.core.service;

import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.stream.Collectors;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import com.egx.core.domain.Role;
import com.egx.core.domain.Subscription;
import com.egx.core.domain.User;
import com.egx.core.domain.enums.AccountStatus;
import com.egx.core.domain.enums.KycStatus;
import com.egx.core.domain.enums.SubscriptionStatus;
import com.egx.core.domain.enums.SubscriptionTier;
import com.egx.core.repository.SubscriptionRepository;
import com.egx.core.repository.UserRepository;

import jakarta.transaction.Transactional;

@Service
public class UserService {

    private final UserRepository userRepository;
    private final SubscriptionRepository subscriptionRepository;

    public UserService(
            UserRepository userRepository,
            SubscriptionRepository subscriptionRepository
    ) {
        this.userRepository = userRepository;
        this.subscriptionRepository = subscriptionRepository;
    }

    @Transactional
    public UserProfile getProfile(Long userId) {
        User user = findUser(userId);
        return toUserProfile(user);
    }

    @Transactional
    public UserProfile updateProfile(Long userId, ProfileUpdateCommand command) {
        User user = findUser(userId);

        user.setFullName(command.fullName().trim());
        user.setPhone(normalizePhone(command.phone()));
        user.setUpdatedAt(LocalDateTime.now(ZoneOffset.UTC));

        User updated = userRepository.save(user);
        return toUserProfile(updated);
    }

    private User findUser(Long userId) {
        return userRepository.findById(userId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "User not found"));
    }

    private UserProfile toUserProfile(User user) {
        SubscriptionTier tier = resolveCurrentTier(user.getId());
        // Convert roles to list of names for response
        List<String> roleNames = user.getRoles().stream()
                .map(Role::getName)
                .collect(Collectors.toList());
        return new UserProfile(
                user.getId(),
                user.getEmail(),
                user.getFullName(),
                user.getPhone(),
                user.getKycStatus(),
                user.getAccountStatus(),
                roleNames,
                tier,
                user.getCreatedAt(),
                user.getUpdatedAt()
        );
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

    private String normalizePhone(String phone) {
        if (phone == null || phone.isBlank()) {
            return null;
        }
        return phone.trim();
    }

    public record ProfileUpdateCommand(String fullName, String phone) {
    }

    public record UserProfile(
            Long userId,
            String email,
            String fullName,
            String phone,
            KycStatus kycStatus,
            AccountStatus accountStatus,
            List<String> roles,
            SubscriptionTier tier,
            LocalDateTime createdAt,
            LocalDateTime updatedAt
    ) {
    }
}
