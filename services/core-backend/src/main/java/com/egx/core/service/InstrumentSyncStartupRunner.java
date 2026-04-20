package com.egx.core.service;

import java.time.Duration;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.context.event.EventListener;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

@Component
public class InstrumentSyncStartupRunner {

    private static final Logger LOGGER = LoggerFactory.getLogger(InstrumentSyncStartupRunner.class);

    private final RestTemplate instrumentSyncRestTemplate;
    private final String aiEngineBaseUrl;

    public InstrumentSyncStartupRunner(
            RestTemplateBuilder restTemplateBuilder,
            @Value("${ai.engine.instrument-sync.connect-timeout-seconds:10}") long connectTimeoutSeconds,
            @Value("${ai.engine.instrument-sync.read-timeout-seconds:90}") long readTimeoutSeconds,
            @Value("${ai.engine.base-url:http://ai-engine:8000}") String aiEngineBaseUrl
    ) {
        this.instrumentSyncRestTemplate = restTemplateBuilder
                .setConnectTimeout(Duration.ofSeconds(Math.max(1, connectTimeoutSeconds)))
                .setReadTimeout(Duration.ofSeconds(Math.max(1, readTimeoutSeconds)))
                .build();
        this.aiEngineBaseUrl = aiEngineBaseUrl;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void triggerInstrumentSyncOnStartup() {
        String syncUrl = aiEngineBaseUrl.replaceAll("/+$", "") + "/instruments/sync";

        try {
            ResponseEntity<String> response = instrumentSyncRestTemplate.getForEntity(syncUrl, String.class);
            if (response.getStatusCode().is2xxSuccessful()) {
                LOGGER.info("Startup instrument sync succeeded via {}", syncUrl);
            } else {
                LOGGER.warn("Startup instrument sync returned non-success status {} via {}", response.getStatusCode(), syncUrl);
            }
        } catch (RestClientException ex) {
            LOGGER.warn("Startup instrument sync timed out or failed via {}. Backend startup continues. Cause={}", syncUrl, ex.getMessage());
        } catch (Exception ex) {
            LOGGER.warn("Startup instrument sync encountered an unexpected error via {}. Backend startup continues.", syncUrl, ex);
        }
    }
}
