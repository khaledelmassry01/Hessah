package com.egx.core.service;

import org.springframework.stereotype.Service;

import com.egx.core.domain.User;
import com.egx.core.domain.enums.SubscriptionStatus;
import com.egx.core.domain.enums.SubscriptionTier;
import com.egx.core.exception.TierAccessDeniedException;
import com.egx.core.repository.SubscriptionRepository;
import com.egx.core.repository.UserRepository;

@Service
public class PremiumAccessService {

    private final SubscriptionRepository subscriptionRepository;
    private final UserRepository userRepository;

    public PremiumAccessService(SubscriptionRepository subscriptionRepository, UserRepository userRepository) {
        this.subscriptionRepository = subscriptionRepository;
        this.userRepository = userRepository;
    }

    public void assertPremium(Long userId) {
        User user = userRepository.findById(userId).orElse(null);
        if (user != null && user.hasAnyRole("PRO", "ADMIN")) {
            return;
        }

        boolean isPremium = subscriptionRepository
                .findFirstByUserIdAndTierAndStatusOrderByStartedAtDesc(
                        userId,
                        SubscriptionTier.PREMIUM,
                        SubscriptionStatus.ACTIVE
                )
                .isPresent();

        if (!isPremium) {
            throw new TierAccessDeniedException("PRO subscription or role is required for this feature");
        }
    }

    public boolean isPremium(Long userId) {
        User user = userRepository.findById(userId).orElse(null);
        if (user != null && user.hasAnyRole("PRO", "ADMIN")) {
            return true;
        }
        return subscriptionRepository
                .findFirstByUserIdAndTierAndStatusOrderByStartedAtDesc(
                        userId,
                        SubscriptionTier.PREMIUM,
                        SubscriptionStatus.ACTIVE
                )
                .isPresent();
    }
}
