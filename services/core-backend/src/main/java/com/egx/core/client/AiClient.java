package com.egx.core.client;

import com.egx.core.client.dto.AiBacktestRequest;
import com.egx.core.client.dto.AiBacktestResponse;
import com.egx.core.client.dto.AiPredictionRequest;
import com.egx.core.client.dto.AiPredictionResponse;

public interface AiClient {
    AiPredictionResponse predict(AiPredictionRequest request);

    AiBacktestResponse backtest(AiBacktestRequest request);
}
