package com.egx.core.service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.net.URI;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.stream.Collectors;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.util.UriComponentsBuilder;

import com.egx.core.domain.MarketDailyBar;
import com.egx.core.domain.StockInstrument;
import com.egx.core.repository.MarketDailyBarRepository;
import com.egx.core.repository.StockInstrumentRepository;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

@Service
public class MarketDataService {

    private static final int SYMBOL_MAX_LENGTH = 16;
    private static final int DB_TRANSACTION_BATCH_SIZE = 1000;
    private static final String EGX_SUFFIX = ".CA";
    private static final String DEFAULT_FMP_API_KEY = "8ID9U3FQCVXMxIJms5jmQxRtQMUBl4aV";
    private static final String DEFAULT_FMP_BASE_URL = "https://financialmodelingprep.com";

    // Hardcoded symbol mapping to guarantee 1:1 compatibility with stock_instruments.
    private static final Map<String, String> CANONICAL_TO_FMP_SYMBOL = Map.ofEntries(
            Map.entry("COMI.CA", "COMI.CA"),
            Map.entry("HRHO.CA", "HRHO.CA"),
            Map.entry("SWDY.CA", "SWDY.CA"),
            Map.entry("ETEL.CA", "ETEL.CA"),
            Map.entry("EFIH.CA", "EFIH.CA"),
            Map.entry("ABUK.CA", "ABUK.CA"),
            Map.entry("FWRY.CA", "FWRY.CA"),
            Map.entry("PHDC.CA", "PHDC.CA"),
            Map.entry("TMGH.CA", "TMGH.CA"),
            Map.entry("ORWE.CA", "ORWE.CA"),
            Map.entry("EAST.CA", "EAST.CA"),
            Map.entry("AMOC.CA", "AMOC.CA"),
            Map.entry("MFPC.CA", "MFPC.CA"),
            Map.entry("SKPC.CA", "SKPC.CA"),
            Map.entry("CCAP.CA", "CCAP.CA"),
            Map.entry("HELI.CA", "HELI.CA"),
            Map.entry("ORAS.CA", "ORAS.CA"),
            Map.entry("EKHO.CA", "EKHO.CA"),
            Map.entry("MICH.CA", "MICH.CA"),
            Map.entry("ALCN.CA", "ALCN.CA"),
            Map.entry("ORHD.CA", "ORHD.CA"),
            Map.entry("JUFO.CA", "JUFO.CA"),
            Map.entry("DOMT.CA", "DOMT.CA"),
            Map.entry("GDWA.CA", "GDWA.CA"),
            Map.entry("CIEB.CA", "CIEB.CA"),
            Map.entry("AUTO.CA", "AUTO.CA"),
            Map.entry("BTFH.CA", "BTFH.CA"),
            Map.entry("OBRI.CA", "OBRI.CA"),
            Map.entry("RAYA.CA", "RAYA.CA"),
            Map.entry("CLHO.CA", "CLHO.CA")
    );

    private final StockInstrumentRepository stockInstrumentRepository;
    private final MarketDailyBarRepository marketDailyBarRepository;
    private final TransactionTemplate transactionTemplate;
    private final RestTemplate restTemplate;
    private final ObjectMapper objectMapper;
    private final String fmpApiKey;
    private final String fmpBaseUrl;

    public MarketDataService(
            StockInstrumentRepository stockInstrumentRepository,
            MarketDailyBarRepository marketDailyBarRepository,
            PlatformTransactionManager transactionManager,
            RestTemplate restTemplate,
            ObjectMapper objectMapper,
            @Value("${fmp.api-key:" + DEFAULT_FMP_API_KEY + "}") String fmpApiKey,
            @Value("${fmp.base-url:" + DEFAULT_FMP_BASE_URL + "}") String fmpBaseUrl
    ) {
        this.stockInstrumentRepository = stockInstrumentRepository;
        this.marketDailyBarRepository = marketDailyBarRepository;
        this.transactionTemplate = new TransactionTemplate(transactionManager);
        this.restTemplate = restTemplate;
        this.objectMapper = objectMapper;
        this.fmpApiKey = fmpApiKey;
        this.fmpBaseUrl = fmpBaseUrl;
    }

    public BulkUpsertResult bulkUpsert(List<MarketDataUpsertCommand> commands) {
        if (commands == null || commands.isEmpty()) {
            return new BulkUpsertResult(0, 0, 0, 0, 0);
        }

        int skipped = 0;
        int inserted = 0;
        int updated = 0;
        int unknownSymbols = 0;

        List<NormalizedMarketData> normalizedRows = new ArrayList<>();

        for (MarketDataUpsertCommand command : commands) {
            NormalizedMarketData normalized = normalize(command);
            if (normalized == null) {
                skipped++;
                continue;
            }
            normalizedRows.add(normalized);
        }

        if (normalizedRows.isEmpty()) {
            return new BulkUpsertResult(commands.size(), 0, 0, skipped, 0);
        }

        for (List<NormalizedMarketData> chunk : partition(normalizedRows, DB_TRANSACTION_BATCH_SIZE)) {
            BulkUpsertResult chunkResult = transactionTemplate.execute(status -> upsertChunk(chunk));
            if (chunkResult == null) {
                throw new IllegalStateException("Market data chunk upsert returned no result");
            }

            inserted += chunkResult.inserted();
            updated += chunkResult.updated();
            skipped += chunkResult.skipped();
            unknownSymbols += chunkResult.unknownSymbols();
        }

        return new BulkUpsertResult(commands.size(), inserted, updated, skipped, unknownSymbols);
    }

    public LatestSnapshotResult refreshLatestCloseSnapshot() {
        if (fmpApiKey == null || fmpApiKey.isBlank()) {
            throw new IllegalStateException("FMP API key is missing");
        }

        List<StockInstrument> instruments = stockInstrumentRepository.findByIsSuspendedFalse();
        if (instruments == null || instruments.isEmpty()) {
            instruments = stockInstrumentRepository.findAll();
        }

        int requested = 0;
        int updated = 0;
        int missingPrice = 0;
        int unknownSymbols = 0;
        int failedRequests = 0;
        List<String> warnings = new ArrayList<>();

        List<StockInstrument> updatedStocks = new ArrayList<>();

        for (StockInstrument stock : instruments) {
            String canonicalSymbol = normalizeSymbol(stock.getSymbol());
            if (canonicalSymbol == null) {
                unknownSymbols++;
                continue;
            }

            requested++;
            String fmpSymbol = CANONICAL_TO_FMP_SYMBOL.get(canonicalSymbol);
            if (fmpSymbol == null || fmpSymbol.isBlank()) {
                unknownSymbols++;
                warnings.add("Missing FMP mapping for symbol " + canonicalSymbol);
                continue;
            }

            try {
                BigDecimal closePrice = fetchLatestClosePrice(fmpSymbol);
                if (closePrice == null || closePrice.compareTo(BigDecimal.ZERO) <= 0) {
                    missingPrice++;
                    continue;
                }

                if (!canonicalSymbol.equals(stock.getSymbol())) {
                    stock.setSymbol(canonicalSymbol);
                }
                stock.setLastPrice(closePrice.setScale(4, RoundingMode.HALF_DOWN));
                stock.setUpdatedAt(LocalDateTime.now());
                updatedStocks.add(stock);
                updated++;
            } catch (Exception ex) {
                failedRequests++;
                if (warnings.size() < 12) {
                    warnings.add("FMP request failed for " + fmpSymbol + ": " + ex.getMessage());
                }
            }
        }

        if (!updatedStocks.isEmpty()) {
            stockInstrumentRepository.saveAll(updatedStocks);
        }

        return new LatestSnapshotResult(
                requested,
                updated,
                missingPrice,
                unknownSymbols,
                failedRequests,
                List.copyOf(warnings)
        );
    }

    private BigDecimal fetchLatestClosePrice(String fmpSymbol) throws Exception {
        URI uri = UriComponentsBuilder
                .fromHttpUrl(resolveFmpBaseUrl())
                .path("/api/v3/quote/{symbol}")
                .queryParam("apikey", fmpApiKey)
                .buildAndExpand(fmpSymbol)
                .encode()
                .toUri();

        ResponseEntity<String> response;
        try {
            response = restTemplate.getForEntity(uri, String.class);
        } catch (RestClientException ex) {
            throw new RuntimeException("HTTP call failed", ex);
        }

        if (!response.getStatusCode().is2xxSuccessful()) {
            throw new RuntimeException("HTTP status " + response.getStatusCode().value());
        }

        String body = response.getBody();
        if (body == null || body.isBlank()) {
            return null;
        }

        JsonNode root = objectMapper.readTree(body);
        JsonNode quoteNode = root;
        if (root.isArray()) {
            if (root.size() == 0) {
                return null;
            }
            quoteNode = root.get(0);
        }

        if (quoteNode == null || quoteNode.isNull()) {
            return null;
        }

        BigDecimal price = asPositiveDecimal(quoteNode.get("price"));
        if (price != null) {
            return price;
        }

        return asPositiveDecimal(quoteNode.get("previousClose"));
    }

    private String resolveFmpBaseUrl() {
        String baseUrl = (fmpBaseUrl == null || fmpBaseUrl.isBlank()) ? DEFAULT_FMP_BASE_URL : fmpBaseUrl;
        return baseUrl.replaceAll("/+$", "");
    }

    private BigDecimal asPositiveDecimal(JsonNode node) {
        if (node == null || node.isNull()) {
            return null;
        }

        BigDecimal value;
        if (node.isNumber()) {
            value = node.decimalValue();
        } else if (node.isTextual()) {
            try {
                value = new BigDecimal(node.asText().trim());
            } catch (NumberFormatException ex) {
                return null;
            }
        } else {
            return null;
        }

        if (value.compareTo(BigDecimal.ZERO) <= 0) {
            return null;
        }

        return value;
    }

    private BulkUpsertResult upsertChunk(List<NormalizedMarketData> chunk) {
        if (chunk == null || chunk.isEmpty()) {
            return new BulkUpsertResult(0, 0, 0, 0, 0);
        }

        int skipped = 0;
        int inserted = 0;
        int updated = 0;
        int unknownSymbols = 0;

        Map<String, List<NormalizedMarketData>> bySymbol = new HashMap<>();

        for (NormalizedMarketData normalized : chunk) {
            bySymbol.computeIfAbsent(normalized.symbol(), key -> new ArrayList<>()).add(normalized);
        }

        if (bySymbol.isEmpty()) {
            return new BulkUpsertResult(chunk.size(), 0, 0, skipped, 0);
        }

        List<String> lookupSymbols = new ArrayList<>(bySymbol.keySet());
        for (String symbol : bySymbol.keySet()) {
            if (symbol.endsWith(EGX_SUFFIX) && symbol.length() > EGX_SUFFIX.length()) {
                lookupSymbols.add(symbol.substring(0, symbol.length() - EGX_SUFFIX.length()));
            }
        }

        Map<String, StockInstrument> stockBySymbol = new HashMap<>();
        for (StockInstrument stock : stockInstrumentRepository.findBySymbolIn(lookupSymbols)) {
            String canonicalSymbol = normalizeSymbol(stock.getSymbol());
            if (canonicalSymbol == null) {
                continue;
            }

            StockInstrument current = stockBySymbol.get(canonicalSymbol);
            if (current == null || stock.getId() < current.getId()) {
                stockBySymbol.put(canonicalSymbol, stock);
            }
        }

        for (Map.Entry<String, List<NormalizedMarketData>> entry : bySymbol.entrySet()) {
            String symbol = entry.getKey();
            List<NormalizedMarketData> symbolItems = entry.getValue();
            StockInstrument stock = stockBySymbol.get(symbol);

            if (stock == null) {
                unknownSymbols += symbolItems.size();
                skipped += symbolItems.size();
                continue;
            }

            LocalDate minDate = symbolItems.stream()
                    .map(NormalizedMarketData::tradeDate)
                    .min(LocalDate::compareTo)
                    .orElse(null);
            LocalDate maxDate = symbolItems.stream()
                    .map(NormalizedMarketData::tradeDate)
                    .max(LocalDate::compareTo)
                    .orElse(null);

            if (minDate == null || maxDate == null) {
                skipped += symbolItems.size();
                continue;
            }

            Map<LocalDate, MarketDailyBar> existingByDate = marketDailyBarRepository
                    .findByStockIdAndTradeDateBetween(stock.getId(), minDate, maxDate)
                    .stream()
                    .collect(Collectors.toMap(MarketDailyBar::getTradeDate, bar -> bar, (left, right) -> left));

            Map<LocalDate, MarketDailyBar> upsertsByDate = new HashMap<>();

            for (NormalizedMarketData item : symbolItems) {
                MarketDailyBar bar = existingByDate.get(item.tradeDate());
                if (bar == null) {
                    bar = new MarketDailyBar();
                    bar.setStockId(stock.getId());
                    bar.setTradeDate(item.tradeDate());
                    existingByDate.put(item.tradeDate(), bar);
                    inserted++;
                } else {
                    updated++;
                }

                bar.setOpenPrice(item.openPrice());
                bar.setHighPrice(item.highPrice());
                bar.setLowPrice(item.lowPrice());
                bar.setClosePrice(item.closePrice());
                bar.setVolume(item.volume());
                bar.setIsHalted(item.halted());

                upsertsByDate.put(item.tradeDate(), bar);
            }

            marketDailyBarRepository.saveAll(upsertsByDate.values());

            NormalizedMarketData latestItem = symbolItems.stream()
                    .max(Comparator.comparing(NormalizedMarketData::tradeDate))
                    .orElse(null);
            if (latestItem != null && latestItem.closePrice() != null) {
                if (!symbol.equals(stock.getSymbol())) {
                    stock.setSymbol(symbol);
                }
                stock.setLastPrice(latestItem.closePrice());
                stock.setUpdatedAt(LocalDateTime.now());
                stockInstrumentRepository.save(stock);
            }
        }

        marketDailyBarRepository.flush();

        return new BulkUpsertResult(chunk.size(), inserted, updated, skipped, unknownSymbols);
    }

    private List<List<NormalizedMarketData>> partition(List<NormalizedMarketData> items, int batchSize) {
        if (batchSize <= 0 || items.isEmpty()) {
            return List.of(items);
        }

        List<List<NormalizedMarketData>> chunks = new ArrayList<>();
        for (int idx = 0; idx < items.size(); idx += batchSize) {
            int end = Math.min(items.size(), idx + batchSize);
            chunks.add(items.subList(idx, end));
        }
        return chunks;
    }

    private NormalizedMarketData normalize(MarketDataUpsertCommand command) {
        if (command == null) {
            return null;
        }

        String symbol = normalizeSymbol(command.symbol());
        if (symbol == null || command.tradeDate() == null) {
            return null;
        }

        BigDecimal closePrice = normalizeRequiredPrice(command.closePrice());
        if (closePrice == null) {
            return null;
        }

        BigDecimal openPrice = normalizeOptionalPrice(command.openPrice(), closePrice);
        BigDecimal highPrice = normalizeOptionalPrice(command.highPrice(), closePrice);
        BigDecimal lowPrice = normalizeOptionalPrice(command.lowPrice(), closePrice);

        BigDecimal maxPrice = max(openPrice, highPrice, lowPrice, closePrice);
        BigDecimal minPrice = min(openPrice, highPrice, lowPrice, closePrice);

        Long volume = command.volume() == null ? 0L : Math.max(0L, command.volume());
        boolean halted = command.halted() != null && command.halted();

        return new NormalizedMarketData(
                symbol,
                command.tradeDate(),
                openPrice,
                maxPrice,
                minPrice,
                closePrice,
                volume,
                halted
        );
    }

    private String normalizeSymbol(String symbol) {
        if (symbol == null || symbol.isBlank()) {
            return null;
        }

        String normalized = symbol.trim().toUpperCase(Locale.ROOT);

        if (normalized.contains(":")) {
            normalized = normalized.substring(normalized.lastIndexOf(':') + 1);
        }

        normalized = normalized.replaceAll("[^A-Z0-9._-]", "");
        if (normalized.isBlank()) {
            return null;
        }

        if (normalized.endsWith(EGX_SUFFIX)) {
            return normalized.length() <= SYMBOL_MAX_LENGTH
                    ? normalized
                    : normalized.substring(0, SYMBOL_MAX_LENGTH);
        }

        if (normalized.contains(".")) {
            normalized = normalized.substring(0, normalized.indexOf('.'));
        }

        normalized = normalized.replaceAll("[^A-Z0-9_-]", "");
        if (normalized.isBlank()) {
            return null;
        }

        String canonical = normalized + EGX_SUFFIX;
        return canonical.length() <= SYMBOL_MAX_LENGTH
                ? canonical
                : canonical.substring(0, SYMBOL_MAX_LENGTH);
    }

    private BigDecimal normalizeRequiredPrice(BigDecimal price) {
        if (price == null || price.compareTo(BigDecimal.ZERO) <= 0) {
            return null;
        }
        return price.setScale(4, RoundingMode.HALF_DOWN);
    }

    private BigDecimal normalizeOptionalPrice(BigDecimal candidate, BigDecimal fallback) {
        if (candidate == null || candidate.compareTo(BigDecimal.ZERO) <= 0) {
            return fallback;
        }
        return candidate.setScale(4, RoundingMode.HALF_DOWN);
    }

    private BigDecimal max(BigDecimal first, BigDecimal second, BigDecimal third, BigDecimal fourth) {
        BigDecimal result = first;
        if (second.compareTo(result) > 0) {
            result = second;
        }
        if (third.compareTo(result) > 0) {
            result = third;
        }
        if (fourth.compareTo(result) > 0) {
            result = fourth;
        }
        return result;
    }

    private BigDecimal min(BigDecimal first, BigDecimal second, BigDecimal third, BigDecimal fourth) {
        BigDecimal result = first;
        if (second.compareTo(result) < 0) {
            result = second;
        }
        if (third.compareTo(result) < 0) {
            result = third;
        }
        if (fourth.compareTo(result) < 0) {
            result = fourth;
        }
        return result;
    }

    public record MarketDataUpsertCommand(
            String symbol,
            LocalDate tradeDate,
            BigDecimal openPrice,
            BigDecimal highPrice,
            BigDecimal lowPrice,
            BigDecimal closePrice,
            Long volume,
            Boolean halted
    ) {
    }

    public record BulkUpsertResult(int received, int inserted, int updated, int skipped, int unknownSymbols) {
    }

    public record LatestSnapshotResult(
            int requested,
            int updated,
            int missingPrice,
            int unknownSymbols,
            int failedRequests,
            List<String> warnings
    ) {
    }

    private record NormalizedMarketData(
            String symbol,
            LocalDate tradeDate,
            BigDecimal openPrice,
            BigDecimal highPrice,
            BigDecimal lowPrice,
            BigDecimal closePrice,
            Long volume,
            boolean halted
    ) {
    }
}
