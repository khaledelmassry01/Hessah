package com.egx.core.service;

import com.egx.core.domain.Wallet;
import com.egx.core.domain.WalletLedgerEntry;
import com.egx.core.domain.enums.LedgerEntryType;
import com.egx.core.domain.enums.LedgerSettlementStatus;
import com.egx.core.exception.InsufficientWalletBalanceException;
import com.egx.core.repository.WalletLedgerEntryRepository;
import com.egx.core.repository.WalletRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.Map;

@Service
public class WalletService {

    private static final int CURRENCY_SCALE = 4;
    private static final BigDecimal FEE_MULTIPLIER = new BigDecimal("0.995");

    private final WalletRepository walletRepository;
    private final WalletLedgerEntryRepository walletLedgerEntryRepository;
    private final SecurityAuditService securityAuditService;

    public WalletService(
            WalletRepository walletRepository,
            WalletLedgerEntryRepository walletLedgerEntryRepository,
            SecurityAuditService securityAuditService
    ) {
        this.walletRepository = walletRepository;
        this.walletLedgerEntryRepository = walletLedgerEntryRepository;
        this.securityAuditService = securityAuditService;
    }

    public Wallet getWalletByUserId(Long userId) {
        return walletRepository.findByUserId(userId)
                .orElseThrow(() -> new IllegalArgumentException("Wallet not found for user: " + userId));
    }

    @Transactional
    public Wallet fundWallet(Long userId, BigDecimal amountEgp) {
        try {
            BigDecimal normalizedAmount = money(amountEgp);
            if (normalizedAmount.compareTo(BigDecimal.ZERO) <= 0) {
                throw new IllegalArgumentException("Funding amount must be greater than zero");
            }

            Wallet wallet = getWalletByUserId(userId);
            wallet.setAvailableBalance(money(defaultIfNull(wallet.getAvailableBalance()).add(normalizedAmount)));
            wallet.setUpdatedAt(LocalDateTime.now());
            wallet = walletRepository.save(wallet);

            persistLedgerEntry(
                    wallet.getId(),
                    LedgerEntryType.DEPOSIT,
                    normalizedAmount,
                    "WALLET_FUND",
                    null,
                    "Wallet funded via API"
            );

            Map<String, Object> details = new LinkedHashMap<>();
            details.put("walletId", wallet.getId());
            details.put("amountEgp", normalizedAmount);
            details.put("availableBalance", wallet.getAvailableBalance());
            securityAuditService.log("WALLET_FUND", userId, "SUCCESS", details);

            return wallet;
        } catch (RuntimeException ex) {
            Map<String, Object> details = new LinkedHashMap<>();
            details.put("amountEgp", amountEgp);
            details.put("reason", ex.getClass().getSimpleName());
            securityAuditService.log("WALLET_FUND", userId, "FAILED", details);
            throw ex;
        }
    }

    @Transactional
    public FeeBufferDeduction deductFeeBuffer(Long userId, BigDecimal requestedAmount, Long referenceId) {
        Wallet wallet = walletRepository.findByUserId(userId)
                .orElseThrow(() -> new IllegalArgumentException("Wallet not found for user: " + userId));

        BigDecimal normalizedRequested = money(requestedAmount);
        if (normalizedRequested.compareTo(BigDecimal.ZERO) <= 0) {
            throw new IllegalArgumentException("Requested amount must be greater than zero");
        }

        BigDecimal availableBalance = defaultIfNull(wallet.getAvailableBalance());
        if (availableBalance.compareTo(normalizedRequested) < 0) {
            throw new InsufficientWalletBalanceException("Insufficient wallet balance for requested investment");
        }

        BigDecimal investableBudget = money(normalizedRequested.multiply(FEE_MULTIPLIER));
        BigDecimal feeAmount = money(normalizedRequested.subtract(investableBudget));

        wallet.setAvailableBalance(money(availableBalance.subtract(normalizedRequested)));
        wallet.setLockedBalance(money(defaultIfNull(wallet.getLockedBalance()).add(investableBudget)));
        walletRepository.save(wallet);

        persistLedgerEntry(
                wallet.getId(),
                LedgerEntryType.FEE_BUFFER,
                feeAmount,
                "PORTFOLIO_RUN",
                referenceId,
                "0.5% fee buffer deducted from requested amount"
        );

        return new FeeBufferDeduction(normalizedRequested, investableBudget, feeAmount);
    }

    @Transactional
    public BigDecimal creditResidual(Long userId, BigDecimal residualAmount, Long referenceId) {
        BigDecimal normalizedResidual = money(residualAmount);
        if (normalizedResidual.compareTo(BigDecimal.ZERO) <= 0) {
            return BigDecimal.ZERO.setScale(CURRENCY_SCALE, RoundingMode.HALF_DOWN);
        }

        Wallet wallet = walletRepository.findByUserId(userId)
                .orElseThrow(() -> new IllegalArgumentException("Wallet not found for user: " + userId));

        BigDecimal currentLocked = defaultIfNull(wallet.getLockedBalance());
        BigDecimal updatedLocked = money(currentLocked.subtract(normalizedResidual));
        if (updatedLocked.compareTo(BigDecimal.ZERO) < 0) {
            updatedLocked = BigDecimal.ZERO.setScale(CURRENCY_SCALE, RoundingMode.HALF_DOWN);
        }

        wallet.setLockedBalance(updatedLocked);
        wallet.setAvailableBalance(money(defaultIfNull(wallet.getAvailableBalance()).add(normalizedResidual)));
        walletRepository.save(wallet);

        persistLedgerEntry(
                wallet.getId(),
                LedgerEntryType.RESIDUAL_RETURN,
                normalizedResidual,
                "PORTFOLIO_RUN",
                referenceId,
                "Residual cash returned after whole-share floor allocation"
        );

        return normalizedResidual;
    }

    private void persistLedgerEntry(
            Long walletId,
            LedgerEntryType entryType,
            BigDecimal amount,
            String referenceType,
            Long referenceId,
            String notes
    ) {
        WalletLedgerEntry entry = new WalletLedgerEntry();
        entry.setWalletId(walletId);
        entry.setEntryType(entryType);
        entry.setAmount(money(amount));
        entry.setReferenceType(referenceType);
        entry.setReferenceId(referenceId);
        entry.setSettlementStatus(LedgerSettlementStatus.N_A);
        entry.setNotes(notes);
        entry.setCreatedAt(LocalDateTime.now());
        walletLedgerEntryRepository.save(entry);
    }

    private BigDecimal money(BigDecimal value) {
        return defaultIfNull(value).setScale(CURRENCY_SCALE, RoundingMode.HALF_DOWN);
    }

    private BigDecimal defaultIfNull(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
    }

    public record FeeBufferDeduction(
            BigDecimal requestedAmount,
            BigDecimal investableBudget,
            BigDecimal feeAmount
    ) {
    }
}
