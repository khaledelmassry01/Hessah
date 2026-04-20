package com.egx.core.security;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class EncryptionKeyProvider {

    private static final String FALLBACK_KEY = "EGXPortfolioEncryptionKey_ChangeMe_2026_32B!";

    private static volatile String activeKey = FALLBACK_KEY;

    public EncryptionKeyProvider(@Value("${app.security.encryption.key:EGXPortfolioEncryptionKey_ChangeMe_2026_32B!}") String configuredKey) {
        if (configuredKey != null && !configuredKey.isBlank()) {
            activeKey = configuredKey.trim();
        }
    }

    public static String currentKey() {
        return activeKey;
    }
}
