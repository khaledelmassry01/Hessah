package com.egx.core.security;

import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.Iterator;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class SecurityRateLimiterService {

    private static final int CLEANUP_THRESHOLD = 20_000;

    private final ConcurrentHashMap<String, WindowCounter> windows = new ConcurrentHashMap<>();

    public RateLimitDecision evaluate(String key, int maxRequests, long windowSeconds) {
        long now = Instant.now().getEpochSecond();
        WindowCounter counter = windows.computeIfAbsent(key, ignored -> new WindowCounter(now));
        RateLimitDecision decision = counter.evaluate(now, maxRequests, windowSeconds);

        if (windows.size() > CLEANUP_THRESHOLD) {
            cleanup(now, windowSeconds * 2);
        }

        return decision;
    }

    private void cleanup(long now, long staleAfterSeconds) {
        Iterator<Map.Entry<String, WindowCounter>> iterator = windows.entrySet().iterator();
        while (iterator.hasNext()) {
            Map.Entry<String, WindowCounter> entry = iterator.next();
            if (entry.getValue().isStale(now, staleAfterSeconds)) {
                iterator.remove();
            }
        }
    }

    private static final class WindowCounter {
        private long windowStart;
        private long lastSeen;
        private int count;

        private WindowCounter(long now) {
            this.windowStart = now;
            this.lastSeen = now;
            this.count = 0;
        }

        private synchronized RateLimitDecision evaluate(long now, int maxRequests, long windowSeconds) {
            this.lastSeen = now;

            if (now - windowStart >= windowSeconds) {
                windowStart = now;
                count = 0;
            }

            if (count >= maxRequests) {
                long retryAfter = Math.max(1, windowSeconds - (now - windowStart));
                return new RateLimitDecision(
                        false,
                        maxRequests,
                        0,
                        retryAfter,
                        windowStart + windowSeconds
                );
            }

            count += 1;
            int remaining = Math.max(0, maxRequests - count);
            long retryAfter = Math.max(1, windowSeconds - (now - windowStart));

            return new RateLimitDecision(
                    true,
                    maxRequests,
                    remaining,
                    retryAfter,
                    windowStart + windowSeconds
            );
        }

        private synchronized boolean isStale(long now, long staleAfterSeconds) {
            return now - lastSeen > staleAfterSeconds;
        }
    }

    public record RateLimitDecision(
            boolean allowed,
            int limit,
            int remaining,
            long retryAfterSeconds,
            long resetEpochSecond
    ) {
    }
}
