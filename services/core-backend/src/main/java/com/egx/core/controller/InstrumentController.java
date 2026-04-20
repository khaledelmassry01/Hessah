package com.egx.core.controller;

import com.egx.core.service.InstrumentSyncService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.List;

@RestController
@RequestMapping({"/instruments", "/api/core/instruments"})
public class InstrumentController {

    private static final Logger LOGGER = LoggerFactory.getLogger(InstrumentController.class);

    private final InstrumentSyncService instrumentSyncService;

    public InstrumentController(InstrumentSyncService instrumentSyncService) {
        this.instrumentSyncService = instrumentSyncService;
    }

    @PostMapping("/bulk")
    public BulkSyncResponse bulkUpsert(@RequestBody(required = false) List<InstrumentBulkItem> items) {
        List<InstrumentBulkItem> payload = items == null ? List.of() : items;
        List<InstrumentSyncService.InstrumentUpsertCommand> commands = new ArrayList<>();
        int malformed = 0;

        for (InstrumentBulkItem item : payload) {
            if (item == null) {
                malformed++;
                continue;
            }

            commands.add(new InstrumentSyncService.InstrumentUpsertCommand(item.symbol(), item.name(), item.sector()));
        }

        try {
            InstrumentSyncService.BulkUpsertResult result = instrumentSyncService.bulkUpsert(commands);

            return new BulkSyncResponse(
                    payload.size(),
                    result.inserted(),
                    result.updated(),
                    result.skipped() + malformed,
                    malformed > 0
                            ? "Instrument synchronization completed with malformed rows skipped"
                            : "Instrument synchronization completed"
            );
        } catch (RuntimeException ex) {
            LOGGER.error("Instrument bulk sync failed, returning safe response", ex);
            return new BulkSyncResponse(
                    payload.size(),
                    0,
                    0,
                    payload.size(),
                    "Instrument synchronization failed safely; all rows skipped"
            );
        }
    }

    public record InstrumentBulkItem(String symbol, String name, String sector) {
    }

    public record BulkSyncResponse(int received, int inserted, int updated, int skipped, String message) {
    }
}
