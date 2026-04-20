package com.egx.core.service;

import com.egx.core.domain.SectorReference;
import com.egx.core.domain.StockInstrument;
import com.egx.core.repository.SectorReferenceRepository;
import com.egx.core.repository.StockInstrumentRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.LocalDateTime;
import java.util.List;

@Service
public class InstrumentSyncService {

    private static final Logger LOGGER = LoggerFactory.getLogger(InstrumentSyncService.class);

    private static final int SYMBOL_MAX_LENGTH = 16;
    private static final int NAME_MAX_LENGTH = 255;
    private static final int SECTOR_CODE_MAX_LENGTH = 64;
    private static final int SECTOR_NAME_MAX_LENGTH = 128;
    private static final String DEFAULT_SECTOR_CODE = "FIN_SERV";
    private static final String DEFAULT_SECTOR_NAME = "Financial Services";

    private final StockInstrumentRepository stockInstrumentRepository;
    private final SectorReferenceRepository sectorReferenceRepository;
    private final TransactionTemplate transactionTemplate;

    public InstrumentSyncService(
            StockInstrumentRepository stockInstrumentRepository,
            SectorReferenceRepository sectorReferenceRepository,
            PlatformTransactionManager transactionManager
    ) {
        this.stockInstrumentRepository = stockInstrumentRepository;
        this.sectorReferenceRepository = sectorReferenceRepository;
        this.transactionTemplate = new TransactionTemplate(transactionManager);
    }

    public BulkUpsertResult bulkUpsert(List<InstrumentUpsertCommand> commands) {
        if (commands == null || commands.isEmpty()) {
            return new BulkUpsertResult(0, 0, 0, 0);
        }

        int inserted = 0;
        int updated = 0;
        int skipped = 0;

        ensureSectorExistsSafely(DEFAULT_SECTOR_CODE, DEFAULT_SECTOR_NAME);

        for (InstrumentUpsertCommand command : commands) {
            if (command == null) {
                skipped++;
                LOGGER.warn("Skipping null instrument command");
                continue;
            }

            try {
                SingleUpsertOutcome outcome = transactionTemplate.execute(status -> upsertSingle(command));
                if (outcome == null) {
                    skipped++;
                    continue;
                }

                inserted += outcome.inserted();
                updated += outcome.updated();
                skipped += outcome.skipped();
            } catch (RuntimeException ex) {
                skipped++;
                LOGGER.warn(
                        "Instrument upsert failed for symbol={} and will be skipped",
                        command.symbol(),
                        ex
                );
            }
        }

        return new BulkUpsertResult(commands.size(), inserted, updated, skipped);
    }

    private SingleUpsertOutcome upsertSingle(InstrumentUpsertCommand command) {
        String symbol = normalizeSymbol(command.symbol());
        if (symbol == null) {
            return new SingleUpsertOutcome(0, 0, 1);
        }

        String name = normalizeName(command.name(), symbol);
        String sectorCode = resolveSectorCode(command.sector());

        StockInstrument existing = stockInstrumentRepository.findBySymbol(symbol).orElse(null);
        LocalDateTime now = LocalDateTime.now();

        if (existing == null) {
            StockInstrument created = new StockInstrument();
            created.setSymbol(symbol);
            created.setName(name);
            created.setSectorCode(sectorCode);
            created.setIsSuspended(false);
            created.setSuspensionReason(null);
            created.setLastPrice(null);
            created.setCreatedAt(now);
            created.setUpdatedAt(now);
            stockInstrumentRepository.saveAndFlush(created);
            return new SingleUpsertOutcome(1, 0, 0);
        }

        existing.setName(name);
        existing.setSectorCode(sectorCode);
        existing.setIsSuspended(false);
        existing.setSuspensionReason(null);
        existing.setUpdatedAt(now);
        stockInstrumentRepository.saveAndFlush(existing);
        return new SingleUpsertOutcome(0, 1, 0);
    }

    private String resolveSectorCode(String rawSector) {
        String normalizedCode = normalizeSectorCode(rawSector);
        if (normalizedCode == null) {
            return DEFAULT_SECTOR_CODE;
        }

        String sectorName = normalizeSectorName(rawSector, normalizedCode);
        if (!ensureSectorExistsSafely(normalizedCode, sectorName)) {
            return DEFAULT_SECTOR_CODE;
        }
        return normalizedCode;
    }

    private boolean ensureSectorExistsSafely(String code, String name) {
        try {
            ensureSectorExists(code, name);
            return true;
        } catch (RuntimeException ex) {
            LOGGER.warn("Sector ensure failed for code={} name={}", code, name, ex);
            return false;
        }
    }

    private void ensureSectorExists(String code, String name) {
        LocalDateTime now = LocalDateTime.now();

        SectorReference existing = sectorReferenceRepository.findByCodeIgnoreCase(code).orElse(null);
        if (existing == null) {
            SectorReference created = new SectorReference();
            created.setCode(code);
            created.setName(truncate(name, SECTOR_NAME_MAX_LENGTH));
            created.setIsActive(true);
            created.setCreatedAt(now);
            created.setUpdatedAt(now);
            sectorReferenceRepository.saveAndFlush(created);
            return;
        }

        boolean changed = false;
        if (!Boolean.TRUE.equals(existing.getIsActive())) {
            existing.setIsActive(true);
            changed = true;
        }

        String normalizedName = truncate(name, SECTOR_NAME_MAX_LENGTH);
        if (normalizedName != null && !normalizedName.isBlank() && !normalizedName.equals(existing.getName())) {
            existing.setName(normalizedName);
            changed = true;
        }

        if (changed) {
            existing.setUpdatedAt(now);
            sectorReferenceRepository.saveAndFlush(existing);
        }
    }

    private String normalizeSymbol(String rawSymbol) {
        if (rawSymbol == null || rawSymbol.isBlank()) {
            return null;
        }

        String normalized = rawSymbol.trim().toUpperCase();

        if (normalized.contains(":")) {
            normalized = normalized.substring(normalized.lastIndexOf(':') + 1);
        }
        if (normalized.contains(".")) {
            normalized = normalized.substring(0, normalized.indexOf('.'));
        }

        normalized = normalized.replaceAll("[^A-Z0-9_-]", "");
        if (normalized.isBlank()) {
            return null;
        }

        return truncate(normalized, SYMBOL_MAX_LENGTH);
    }

    private String normalizeName(String rawName, String fallbackSymbol) {
        if (rawName == null || rawName.isBlank()) {
            return truncate(fallbackSymbol, NAME_MAX_LENGTH);
        }
        return truncate(rawName.trim(), NAME_MAX_LENGTH);
    }

    private String normalizeSectorCode(String rawSector) {
        if (rawSector == null || rawSector.isBlank()) {
            return null;
        }

        String normalized = rawSector.trim().toUpperCase();
        normalized = normalized.replaceAll("[^A-Z0-9]+", "_");
        normalized = normalized.replaceAll("_+", "_");
        normalized = normalized.replaceAll("^_+", "");
        normalized = normalized.replaceAll("_+$", "");

        if (normalized.isBlank()) {
            return null;
        }

        return truncate(normalized, SECTOR_CODE_MAX_LENGTH);
    }

    private String normalizeSectorName(String rawSector, String normalizedCode) {
        if (rawSector != null && !rawSector.isBlank()) {
            return rawSector.trim();
        }

        return normalizedCode.replace('_', ' ');
    }

    private String truncate(String value, int maxLength) {
        if (value == null) {
            return null;
        }

        if (value.length() <= maxLength) {
            return value;
        }

        return value.substring(0, maxLength);
    }

    public record InstrumentUpsertCommand(String symbol, String name, String sector) {
    }

    public record BulkUpsertResult(int received, int inserted, int updated, int skipped) {
    }

    private record SingleUpsertOutcome(int inserted, int updated, int skipped) {
    }
}
