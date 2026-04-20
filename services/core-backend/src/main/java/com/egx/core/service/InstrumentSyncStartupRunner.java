package com.egx.core.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

@Component
public class InstrumentSyncStartupRunner {

    private static final Logger LOGGER = LoggerFactory.getLogger(InstrumentSyncStartupRunner.class);

    private final RestTemplate restTemplate;
    private final String aiEngineBaseUrl;

    public InstrumentSyncStartupRunner(
            RestTemplate restTemplate,
            @Value("${ai.engine.base-url:http://ai-engine:8000}") String aiEngineBaseUrl
    ) {
        this.restTemplate = restTemplate;
        this.aiEngineBaseUrl = aiEngineBaseUrl;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void triggerInstrumentSyncOnStartup() {
        String syncUrl = aiEngineBaseUrl.replaceAll("/+$", "") + "/instruments/sync";

        try {
            ResponseEntity<String> response = restTemplate.getForEntity(syncUrl, String.class);
            if (response.getStatusCode().is2xxSuccessful()) {
                LOGGER.info("Startup instrument sync succeeded via {}", syncUrl);
            } else {
                LOGGER.warn("Startup instrument sync returned non-success status {} via {}", response.getStatusCode(), syncUrl);
            }
        } catch (RestClientException ex) {
            LOGGER.warn("Startup instrument sync failed via {}: {}", syncUrl, ex.getMessage());
        }
    }
}
