package com.egx.core.repository;

import com.egx.core.domain.Subscription;
import com.egx.core.domain.enums.SubscriptionStatus;
import com.egx.core.domain.enums.SubscriptionTier;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface SubscriptionRepository extends JpaRepository<Subscription, Long> {
    Optional<Subscription> findFirstByUserIdAndTierAndStatusOrderByStartedAtDesc(
            Long userId,
            SubscriptionTier tier,
            SubscriptionStatus status
    );
}
