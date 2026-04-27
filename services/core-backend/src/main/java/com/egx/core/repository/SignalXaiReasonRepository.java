package com.egx.core.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import com.egx.core.domain.SignalXaiReason;

@Repository
public interface SignalXaiReasonRepository extends JpaRepository<SignalXaiReason, Long> {

    List<SignalXaiReason> findBySignalIdOrderByReasonOrderAsc(Long signalId);

    List<SignalXaiReason> findBySignalIdInOrderBySignalIdAscReasonOrderAsc(List<Long> signalIds);

    void deleteBySignalId(Long signalId);
}
