package com.egx.core.service;

import java.time.LocalDateTime;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import com.egx.core.domain.SectorReference;
import com.egx.core.domain.StockInstrument;
import com.egx.core.repository.SectorReferenceRepository;
import com.egx.core.repository.StockInstrumentRepository;

@Service
public class InstrumentSyncService {

    private static final Logger LOGGER = LoggerFactory.getLogger(InstrumentSyncService.class);

    private static final int SYMBOL_MAX_LENGTH = 16;
    private static final int NAME_MAX_LENGTH = 255;
    private static final int SECTOR_CODE_MAX_LENGTH = 64;
    private static final int SECTOR_NAME_MAX_LENGTH = 128;
    private static final String EGX_SUFFIX = ".CA";
    private static final String DEFAULT_SECTOR_CODE = "FIN_SERV";
    private static final String DEFAULT_SECTOR_NAME = "Financial Services";

    private static final List<InstrumentUpsertCommand> EGX30_FALLBACK = List.of(
            new InstrumentUpsertCommand("COMI.CA", "Commercial International Bank", "Banks"),
            new InstrumentUpsertCommand("HRHO.CA", "EFG Holding", "Financial Services"),
            new InstrumentUpsertCommand("SWDY.CA", "Elsewedy Electric", "Industrials"),
            new InstrumentUpsertCommand("ETEL.CA", "Telecom Egypt", "Telecommunications"),
            new InstrumentUpsertCommand("EFIH.CA", "eFinance Investment Group", "Technology"),
            new InstrumentUpsertCommand("ABUK.CA", "Abu Qir Fertilizers", "Materials"),
            new InstrumentUpsertCommand("FWRY.CA", "Fawry", "Technology"),
            new InstrumentUpsertCommand("PHDC.CA", "Palm Hills Development", "Real Estate"),
            new InstrumentUpsertCommand("TMGH.CA", "Talaat Moustafa Group", "Real Estate"),
            new InstrumentUpsertCommand("ORWE.CA", "Oriental Weavers", "Consumer Discretionary"),
            new InstrumentUpsertCommand("EAST.CA", "Eastern Company", "Consumer Staples"),
            new InstrumentUpsertCommand("AMOC.CA", "Alexandria Mineral Oils", "Energy"),
            new InstrumentUpsertCommand("MFPC.CA", "Misr Fertilizers Production", "Materials"),
            new InstrumentUpsertCommand("SKPC.CA", "Sidi Kerir Petrochemicals", "Materials"),
            new InstrumentUpsertCommand("CCAP.CA", "Citadel Capital", "Financial Services"),
            new InstrumentUpsertCommand("HELI.CA", "Heliopolis Housing", "Real Estate"),
            new InstrumentUpsertCommand("PACH.CA", "Paint and Chemicals Industries", "Materials"),
            new InstrumentUpsertCommand("EKHO.CA", "Egypt Kuwait Holding", "Industrials"),
            new InstrumentUpsertCommand("MICH.CA", "Misr Chemical Industries", "Materials"),
            new InstrumentUpsertCommand("ALCN.CA", "Alexandria Containers", "Industrials"),
            new InstrumentUpsertCommand("ESRS.CA", "Ezz Steel", "Materials"),
            new InstrumentUpsertCommand("JUFO.CA", "Juhayna Food Industries", "Consumer Staples"),
            new InstrumentUpsertCommand("DOMT.CA", "Domty", "Consumer Staples"),
            new InstrumentUpsertCommand("GDWA.CA", "Gadwa for Industrial Development", "Financial Services"),
            new InstrumentUpsertCommand("CIEB.CA", "Credit Agricole Egypt", "Banks"),
            new InstrumentUpsertCommand("AUTO.CA", "GB Corp", "Consumer Discretionary"),
            new InstrumentUpsertCommand("BTFH.CA", "Beltone Holding", "Financial Services"),
            new InstrumentUpsertCommand("OBRI.CA", "Obour Land", "Consumer Staples"),
            new InstrumentUpsertCommand("RAYA.CA", "Raya Holding", "Technology"),
            new InstrumentUpsertCommand("CLHO.CA", "Cleopatra Hospitals", "Healthcare")
    );

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
        List<InstrumentUpsertCommand> payload = commands == null ? List.of() : commands;
        if (payload.isEmpty()) {
            return seedFallbackUniverse();
        }

        int inserted = 0;
        int updated = 0;
        int skipped = 0;
        int malformed = 0;

        ensureSectorExistsSafely(DEFAULT_SECTOR_CODE, DEFAULT_SECTOR_NAME);

        Map<String, InstrumentUpsertCommand> deduplicated = new LinkedHashMap<>();
        for (InstrumentUpsertCommand command : payload) {
            if (command == null) {
                malformed++;
                LOGGER.warn("Skipping null instrument command");
                continue;
            }

            String canonicalSymbol = normalizeSymbol(command.symbol());
            if (canonicalSymbol == null) {
                malformed++;
                continue;
            }

            deduplicated.put(
                    canonicalSymbol,
                    new InstrumentUpsertCommand(
                            canonicalSymbol,
                            normalizeName(command.name(), canonicalSymbol),
                            command.sector()
                    )
            );
        }

        for (InstrumentUpsertCommand command : deduplicated.values()) {
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

        if (inserted + updated == 0) {
            BulkUpsertResult fallback = seedFallbackUniverse();
            inserted += fallback.inserted();
            updated += fallback.updated();
            skipped += fallback.skipped();
        }

        skipped += malformed;
        return new BulkUpsertResult(payload.size(), inserted, updated, skipped);
    }

    public List<InstrumentCatalogItem> listInstrumentCatalog() {
        Map<String, InstrumentCatalogItem> byCanonicalSymbol = new LinkedHashMap<>();

        for (StockInstrument stock : stockInstrumentRepository.findByIsSuspendedFalse()) {
            if (stock.getId() == null) {
                continue;
            }

            String canonicalSymbol = normalizeSymbol(stock.getSymbol());
            if (canonicalSymbol == null) {
                continue;
            }

            InstrumentCatalogItem current = byCanonicalSymbol.get(canonicalSymbol);
            if (current == null || stock.getId() < current.instrumentId()) {
                byCanonicalSymbol.put(
                        canonicalSymbol,
                        new InstrumentCatalogItem(
                                stock.getId(),
                                canonicalSymbol,
                                normalizeName(stock.getName(), canonicalSymbol),
                                stock.getSectorCode()
                        )
                );
            }
        }

        return byCanonicalSymbol.values()
                .stream()
                .sorted(Comparator.comparing(InstrumentCatalogItem::symbol))
                .toList();
    }

    private BulkUpsertResult seedFallbackUniverse() {
        int inserted = 0;
        int updated = 0;
        int skipped = 0;

        ensureSectorExistsSafely(DEFAULT_SECTOR_CODE, DEFAULT_SECTOR_NAME);

        for (InstrumentUpsertCommand command : EGX30_FALLBACK) {
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
                LOGGER.warn("Fallback instrument upsert failed for symbol={}", command.symbol(), ex);
            }
        }

        return new BulkUpsertResult(EGX30_FALLBACK.size(), inserted, updated, skipped);
    }

    private SingleUpsertOutcome upsertSingle(InstrumentUpsertCommand command) {
        String symbol = normalizeSymbol(command.symbol());
        if (symbol == null) {
            return new SingleUpsertOutcome(0, 0, 1);
        }

        String name = normalizeName(command.name(), symbol);
        String sectorCode = resolveSectorCode(command.sector());

        StockInstrument existing = findExistingBySymbolAliases(symbol);
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

        if (!symbol.equals(existing.getSymbol())) {
            existing.setSymbol(symbol);
        }

        existing.setName(name);
        existing.setSectorCode(sectorCode);
        existing.setIsSuspended(false);
        existing.setSuspensionReason(null);
        existing.setUpdatedAt(now);
        stockInstrumentRepository.saveAndFlush(existing);
        return new SingleUpsertOutcome(0, 1, 0);
    }

    private StockInstrument findExistingBySymbolAliases(String canonicalSymbol) {
        StockInstrument existing = stockInstrumentRepository.findBySymbol(canonicalSymbol).orElse(null);
        if (existing != null) {
            return existing;
        }

        if (!canonicalSymbol.endsWith(EGX_SUFFIX)) {
            return null;
        }

        String legacySymbol = canonicalSymbol.substring(0, canonicalSymbol.length() - EGX_SUFFIX.length());
        if (legacySymbol.isBlank()) {
            return null;
        }

        return stockInstrumentRepository.findBySymbol(legacySymbol).orElse(null);
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

        String normalized = rawSymbol.trim().toUpperCase(Locale.ROOT);

        if (normalized.contains(":")) {
            normalized = normalized.substring(normalized.lastIndexOf(':') + 1);
        }

        normalized = normalized.replaceAll("[^A-Z0-9._-]", "");
        if (normalized.isBlank()) {
            return null;
        }

        if (normalized.endsWith(EGX_SUFFIX)) {
            return truncate(normalized, SYMBOL_MAX_LENGTH);
        }

        if (normalized.contains(".")) {
            normalized = normalized.substring(0, normalized.indexOf('.'));
        }

        normalized = normalized.replaceAll("[^A-Z0-9_-]", "");
        if (normalized.isBlank()) {
            return null;
        }

        return truncate(normalized + EGX_SUFFIX, SYMBOL_MAX_LENGTH);
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

        String candidate = rawSector.trim().toUpperCase(Locale.ROOT)
                .replace('.', ' ')
                .replace('-', ' ')
                .replace('/', ' ')
                .replaceAll("\\s+", " ");

        return switch (candidate) {
            case "BANKS" -> "BANKS";
            case "FIN SERV", "FIN_SERV", "FINANCIAL SERVICES", "FINANCIAL_SERVICES" -> "FIN_SERV";
            case "INDUSTRIAL", "INDUSTRIALS" -> "INDUSTRIALS";
            case "REAL ESTATE", "REAL_ESTATE" -> "REAL_ESTATE";
            case "TELECOMMUNICATION", "TELECOMMUNICATIONS", "TELECOM" -> "TELECOM";
            case "ENERGY" -> "ENERGY";
            case "CONSUMER", "CONSUMER STAPLES", "CONSUMER DISCRETIONARY",
                 "CONSUMER_NON_CYCLICAL", "CONSUMER_CYCLICAL" -> "CONSUMER";
            case "HEALTHCARE", "HEALTH CARE" -> "HEALTHCARE";
            case "MATERIAL", "MATERIALS" -> "MATERIALS";
            case "TECH", "TECHNOLOGY" -> "TECHNOLOGY";
            default -> {
                String normalized = candidate.replaceAll("[^A-Z0-9]+", "_");
                normalized = normalized.replaceAll("_+", "_");
                normalized = normalized.replaceAll("^_+", "");
                normalized = normalized.replaceAll("_+$", "");
                if (normalized.isBlank()) {
                    yield null;
                }
                yield truncate(normalized, SECTOR_CODE_MAX_LENGTH);
            }
        };
    }

    private String normalizeSectorName(String rawSector, String normalizedCode) {
        if (rawSector != null && !rawSector.isBlank()) {
            return rawSector.trim();
        }

        return switch (normalizedCode) {
            case "BANKS" -> "Banks";
            case "FIN_SERV" -> "Financial Services";
            case "INDUSTRIALS" -> "Industrials";
            case "REAL_ESTATE" -> "Real Estate";
            case "TELECOM" -> "Telecommunications";
            case "ENERGY" -> "Energy";
            case "CONSUMER" -> "Consumer";
            case "HEALTHCARE" -> "Healthcare";
            case "MATERIALS" -> "Materials";
            case "TECHNOLOGY" -> "Technology";
            default -> normalizedCode.replace('_', ' ');
        };
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

    public record InstrumentCatalogItem(Long instrumentId, String symbol, String name, String sectorCode) {
    }

    private record SingleUpsertOutcome(int inserted, int updated, int skipped) {
    }
}
