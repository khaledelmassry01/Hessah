package com.egx.core.service;

import com.egx.core.domain.AiPredictionAudit;
import com.egx.core.domain.AllocationExecution;
import com.egx.core.domain.PortfolioRun;
import com.egx.core.domain.StockInstrument;
import com.egx.core.domain.WalletLedgerEntry;
import com.egx.core.domain.enums.LedgerEntryType;
import com.egx.core.repository.AiPredictionAuditRepository;
import com.egx.core.repository.AllocationExecutionRepository;
import com.egx.core.repository.PortfolioRunRepository;
import com.egx.core.repository.StockInstrumentRepository;
import com.egx.core.repository.WalletLedgerEntryRepository;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

@Service
public class TearSheetService {

    private static final int MONEY_SCALE = 4;
    private static final BigDecimal ZERO = BigDecimal.ZERO.setScale(MONEY_SCALE, RoundingMode.HALF_DOWN);

    private final PortfolioRunRepository portfolioRunRepository;
    private final AllocationExecutionRepository allocationExecutionRepository;
    private final WalletLedgerEntryRepository walletLedgerEntryRepository;
    private final StockInstrumentRepository stockInstrumentRepository;
    private final AiPredictionAuditRepository aiPredictionAuditRepository;
    private final ObjectMapper objectMapper;

    public TearSheetService(
            PortfolioRunRepository portfolioRunRepository,
            AllocationExecutionRepository allocationExecutionRepository,
            WalletLedgerEntryRepository walletLedgerEntryRepository,
            StockInstrumentRepository stockInstrumentRepository,
            AiPredictionAuditRepository aiPredictionAuditRepository,
            ObjectMapper objectMapper
    ) {
        this.portfolioRunRepository = portfolioRunRepository;
        this.allocationExecutionRepository = allocationExecutionRepository;
        this.walletLedgerEntryRepository = walletLedgerEntryRepository;
        this.stockInstrumentRepository = stockInstrumentRepository;
        this.aiPredictionAuditRepository = aiPredictionAuditRepository;
        this.objectMapper = objectMapper;
    }

    public TearSheetResponse generate(Long portfolioRunId) {
        PortfolioRun run = portfolioRunRepository.findById(portfolioRunId)
                .orElseThrow(() -> new IllegalArgumentException("Portfolio run not found: " + portfolioRunId));

        List<AllocationExecution> allocations = allocationExecutionRepository.findByPortfolioRunId(portfolioRunId);
        Map<Long, StockInstrument> instrumentsById = stockInstrumentRepository
                .findAllById(
                        allocations.stream().map(AllocationExecution::getStockId).collect(Collectors.toSet())
                )
                .stream()
                .collect(Collectors.toMap(StockInstrument::getId, Function.identity()));

        BigDecimal totalInvested = allocations.stream()
                .map(AllocationExecution::getExecutedAmountEgp)
                .filter(v -> v != null)
                .reduce(BigDecimal.ZERO, BigDecimal::add)
                .setScale(MONEY_SCALE, RoundingMode.HALF_DOWN);

        BigDecimal feeBuffer = sumLedgerEntries(portfolioRunId, LedgerEntryType.FEE_BUFFER);
        BigDecimal residualCash = sumLedgerEntries(portfolioRunId, LedgerEntryType.RESIDUAL_RETURN);
        BigDecimal expectedRoi = extractExpectedRoi(portfolioRunId);

        List<AssetLine> assetLines = new ArrayList<>();
        for (AllocationExecution allocation : allocations) {
            StockInstrument stock = instrumentsById.get(allocation.getStockId());
            String symbol = stock == null ? "UNKNOWN" : stock.getSymbol();
            String sector = stock == null ? "UNCLASSIFIED" : stock.getSectorCode();

            assetLines.add(new AssetLine(
                    symbol,
                    sector,
                    sharesOrZero(allocation.getExecutedShares()),
                    money(allocation.getExecutedAmountEgp())
            ));
        }

        return new TearSheetResponse(
                run.getId(),
                run.getUserId(),
                run.getModelVersion(),
                run.getRunStatus().name(),
                money(run.getRequestedAmountEgp()),
                totalInvested,
                feeBuffer,
                residualCash,
                expectedRoi,
                assetLines
        );
    }

    private BigDecimal sumLedgerEntries(Long portfolioRunId, LedgerEntryType entryType) {
        List<WalletLedgerEntry> entries = walletLedgerEntryRepository.findByReferenceIdAndEntryType(portfolioRunId, entryType);
        return entries.stream()
                .map(WalletLedgerEntry::getAmount)
                .filter(v -> v != null)
                .reduce(BigDecimal.ZERO, BigDecimal::add)
                .setScale(MONEY_SCALE, RoundingMode.HALF_DOWN);
    }

    private BigDecimal extractExpectedRoi(Long portfolioRunId) {
        return aiPredictionAuditRepository.findTopByPortfolioRunIdOrderByCreatedAtDesc(portfolioRunId)
                .map(this::extractExpectedRoiFromAudit)
                .orElse(ZERO);
    }

    private BigDecimal extractExpectedRoiFromAudit(AiPredictionAudit audit) {
        if (audit.getResponseJson() == null || audit.getResponseJson().isBlank()) {
            return ZERO;
        }

        try {
            JsonNode root = objectMapper.readTree(audit.getResponseJson());
            JsonNode expectedReturnNode = root.path("expected_return");
            if (expectedReturnNode.isMissingNode() || expectedReturnNode.isNull()) {
                return ZERO;
            }
            return new BigDecimal(expectedReturnNode.asText("0"))
                    .setScale(MONEY_SCALE, RoundingMode.HALF_DOWN);
        } catch (NumberFormatException | IOException ex) {
            return ZERO;
        }
    }

    private Long sharesOrZero(Long value) {
        return value == null ? 0L : value;
    }

    private BigDecimal money(BigDecimal value) {
        if (value == null) {
            return ZERO;
        }
        return value.setScale(MONEY_SCALE, RoundingMode.HALF_DOWN);
    }

    public record TearSheetResponse(
            Long portfolioRunId,
            Long userId,
            String modelVersion,
            String runStatus,
            BigDecimal requestedAmount,
            BigDecimal totalInvested,
            BigDecimal feeBuffer,
            BigDecimal residualCash,
            BigDecimal expectedRoi,
            List<AssetLine> assets
    ) {
    }

    public record AssetLine(
            String symbol,
            String sector,
            Long shares,
            BigDecimal totalPrice
    ) {
    }
}
