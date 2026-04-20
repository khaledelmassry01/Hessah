package com.egx.core.service;

import com.egx.core.domain.enums.SubscriptionStatus;
import com.egx.core.domain.enums.SubscriptionTier;
import com.egx.core.exception.TierAccessDeniedException;
import com.egx.core.repository.SubscriptionRepository;
import org.springframework.stereotype.Service;

@Service
public class PremiumAccessService {

    private final SubscriptionRepository subscriptionRepository;

    public PremiumAccessService(SubscriptionRepository subscriptionRepository) {
        this.subscriptionRepository = subscriptionRepository;
    }

    public void assertPremium(Long userId) {
        boolean isPremium = subscriptionRepository
                .findFirstByUserIdAndTierAndStatusOrderByStartedAtDesc(
                        userId,
                        SubscriptionTier.PREMIUM,
                        SubscriptionStatus.ACTIVE
                )
                .isPresent();

        if (!isPremium) {
            throw new TierAccessDeniedException("PREMIUM subscription is required for this feature");
        }
    }

    public boolean isPremium(Long userId) {
        return subscriptionRepository
                .findFirstByUserIdAndTierAndStatusOrderByStartedAtDesc(
                        userId,
                        SubscriptionTier.PREMIUM,
                        SubscriptionStatus.ACTIVE
                )
                .isPresent();
    }
}
