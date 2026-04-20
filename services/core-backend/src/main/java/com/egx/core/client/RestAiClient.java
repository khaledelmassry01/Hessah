package com.egx.core.client;

import com.egx.core.client.dto.AiBacktestRequest;
import com.egx.core.client.dto.AiBacktestResponse;
import com.egx.core.client.dto.AiPredictionRequest;
import com.egx.core.client.dto.AiPredictionResponse;
import com.egx.core.exception.AiIntegrationException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

@Component
public class RestAiClient implements AiClient {

    private final RestTemplate restTemplate;
    private final String aiEngineBaseUrl;

    public RestAiClient(
            RestTemplate restTemplate,
            @Value("${ai.engine.base-url:http://ai-engine:8000}") String aiEngineBaseUrl
    ) {
        this.restTemplate = restTemplate;
        this.aiEngineBaseUrl = aiEngineBaseUrl;
    }

    @Override
    public AiPredictionResponse predict(AiPredictionRequest request) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        HttpEntity<AiPredictionRequest> entity = new HttpEntity<>(request, headers);

        try {
            ResponseEntity<AiPredictionResponse> response = restTemplate.exchange(
                    aiEngineBaseUrl + "/predict",
                    HttpMethod.POST,
                    entity,
                    AiPredictionResponse.class
            );

            if (!response.getStatusCode().is2xxSuccessful() || response.getBody() == null) {
                throw new AiIntegrationException("AI engine returned an invalid response");
            }

            return response.getBody();
        } catch (RestClientException ex) {
            throw new AiIntegrationException("AI engine call failed", ex);
        }
    }

    @Override
    public AiBacktestResponse backtest(AiBacktestRequest request) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        HttpEntity<AiBacktestRequest> entity = new HttpEntity<>(request, headers);

        try {
            ResponseEntity<AiBacktestResponse> response = restTemplate.exchange(
                    aiEngineBaseUrl + "/backtest",
                    HttpMethod.POST,
                    entity,
                    AiBacktestResponse.class
            );

            if (!response.getStatusCode().is2xxSuccessful() || response.getBody() == null) {
                throw new AiIntegrationException("AI backtest returned an invalid response");
            }

            return response.getBody();
        } catch (RestClientException ex) {
            throw new AiIntegrationException("AI backtest call failed", ex);
        }
    }
}
