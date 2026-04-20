package com.egx.core.service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.stream.Collectors;

import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import com.egx.core.domain.MarketDailyBar;
import com.egx.core.domain.StockInstrument;
import com.egx.core.repository.MarketDailyBarRepository;
import com.egx.core.repository.StockInstrumentRepository;

@Service
public class MarketDataService {

    private static final int SYMBOL_MAX_LENGTH = 16;
    private static final int DB_TRANSACTION_BATCH_SIZE = 1000;
    private static final String EGX_SUFFIX = ".CA";

    private final StockInstrumentRepository stockInstrumentRepository;
    private final MarketDailyBarRepository marketDailyBarRepository;
    private final TransactionTemplate transactionTemplate;

    public MarketDataService(
            StockInstrumentRepository stockInstrumentRepository,
            MarketDailyBarRepository marketDailyBarRepository,
            PlatformTransactionManager transactionManager
    ) {
        this.stockInstrumentRepository = stockInstrumentRepository;
        this.marketDailyBarRepository = marketDailyBarRepository;
        this.transactionTemplate = new TransactionTemplate(transactionManager);
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
