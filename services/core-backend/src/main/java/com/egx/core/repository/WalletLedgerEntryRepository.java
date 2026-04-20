package com.egx.core.repository;

import com.egx.core.domain.WalletLedgerEntry;
import com.egx.core.domain.enums.LedgerEntryType;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface WalletLedgerEntryRepository extends JpaRepository<WalletLedgerEntry, Long> {
	List<WalletLedgerEntry> findByReferenceIdAndEntryType(Long referenceId, LedgerEntryType entryType);
}
