package com.egx.core.controller;

import com.egx.core.service.MarketDataService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

@RestController
@RequestMapping({"/market-data", "/api/core/market-data"})
public class MarketDataController {

    private final MarketDataService marketDataService;

    public MarketDataController(MarketDataService marketDataService) {
        this.marketDataService = marketDataService;
    }

    @PostMapping("/bulk")
    public BulkSyncResponse bulkUpsert(@RequestBody(required = false) List<MarketDataBulkItem> items) {
        List<MarketDataBulkItem> payload = items == null ? List.of() : items;

        List<MarketDataService.MarketDataUpsertCommand> commands = payload.stream()
                .map(item -> new MarketDataService.MarketDataUpsertCommand(
                        item.symbol(),
                        item.tradeDate(),
                        item.openPrice(),
                        item.highPrice(),
                        item.lowPrice(),
                        item.closePrice(),
                        item.volume(),
                        item.halted()
                ))
                .toList();

        MarketDataService.BulkUpsertResult result = marketDataService.bulkUpsert(commands);

        return new BulkSyncResponse(
                result.received(),
                result.inserted(),
                result.updated(),
                result.skipped(),
                result.unknownSymbols(),
                "Market data synchronization completed"
        );
    }

    public record MarketDataBulkItem(
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

    public record BulkSyncResponse(
            int received,
            int inserted,
            int updated,
            int skipped,
            int unknownSymbols,
            String message
    ) {
    }
}
