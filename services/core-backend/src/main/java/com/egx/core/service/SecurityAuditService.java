package com.egx.core.service;

import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import com.egx.core.domain.SecurityAuditLog;
import com.egx.core.repository.SecurityAuditLogRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

import jakarta.servlet.http.HttpServletRequest;

@Service
public class SecurityAuditService {

    private final SecurityAuditLogRepository securityAuditLogRepository;
    private final ObjectMapper objectMapper;
    private final TransactionTemplate requiresNewTransaction;
    private final AtomicBoolean databasePersistenceEnabled = new AtomicBoolean(true);

    public SecurityAuditService(
            SecurityAuditLogRepository securityAuditLogRepository,
            ObjectMapper objectMapper,
            PlatformTransactionManager transactionManager
    ) {
        this.securityAuditLogRepository = securityAuditLogRepository;
        this.objectMapper = objectMapper;
        this.requiresNewTransaction = new TransactionTemplate(transactionManager);
        this.requiresNewTransaction.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    public void log(String action, Long userId, String outcome, Map<String, Object> details) {
        if (!databasePersistenceEnabled.get()) {
            logToConsole(action, userId, outcome, details, null);
            return;
        }

        try {
            requiresNewTransaction.executeWithoutResult(status -> {
                HttpServletRequest request = resolveCurrentRequest();

                SecurityAuditLog log = new SecurityAuditLog();
                log.setUserId(userId);
                log.setAction(truncate(action, 64));
                log.setOutcome(truncate(outcome, 16));
                log.setIpAddress(truncate(resolveClientIp(request), 64));
                log.setUserAgent(truncate(resolveUserAgent(request), 512));
                log.setDetailsJson(toJson(details));
                log.setCreatedAt(LocalDateTime.now(ZoneOffset.UTC));

                securityAuditLogRepository.save(log);
            });
        } catch (Exception ex) {
            if (isMissingAuditTable(ex)) {
                databasePersistenceEnabled.set(false);
                System.out.println(
                        "Table security_audit_logs is unavailable. Disabling DB audit persistence and falling back to console logs."
                );
            } else {
                System.out.println(
                        "Security audit log DB persistence failed for action="
                                + truncate(action, 64)
                                + " userId="
                                + userId
                                + " cause="
                                + ex.getClass().getSimpleName()
                                + ": "
                                + ex.getMessage()
                );
            }

            logToConsole(action, userId, outcome, details, ex);
        }
    }

    private boolean isMissingAuditTable(Throwable throwable) {
        Throwable current = throwable;
        while (current != null) {
            String message = current.getMessage();
            if (message != null) {
                String normalized = message.toLowerCase(Locale.ROOT);
                if (normalized.contains("security_audit_logs") && (
                        normalized.contains("doesn't exist")
                                || normalized.contains("does not exist")
                                || normalized.contains("table")
                                || normalized.contains("42s02")
                                || normalized.contains("1146")
                )) {
                    return true;
                }
            }
            current = current.getCause();
        }

        return false;
    }

    private void logToConsole(
            String action,
            Long userId,
            String outcome,
            Map<String, Object> details,
            Exception ex
    ) {
        String detailsJson = toJson(details);
        String message = "SECURITY_AUDIT_FALLBACK action="
            + truncate(action, 64)
            + " userId="
            + userId
            + " outcome="
            + truncate(outcome, 16)
            + " details="
            + detailsJson;

        if (ex == null) {
            System.out.println(message);
            return;
        }

        System.out.println(message);
        ex.printStackTrace(System.out);
    }

    private HttpServletRequest resolveCurrentRequest() {
        if (!(RequestContextHolder.getRequestAttributes() instanceof ServletRequestAttributes attributes)) {
            return null;
        }
        return attributes.getRequest();
    }

    private String resolveClientIp(HttpServletRequest request) {
        if (request == null) {
            return null;
        }

        String forwardedFor = request.getHeader("X-Forwarded-For");
        if (forwardedFor != null && !forwardedFor.isBlank()) {
            String[] values = forwardedFor.split(",");
            if (values.length > 0 && !values[0].isBlank()) {
                return values[0].trim();
            }
        }

        return request.getRemoteAddr();
    }

    private String resolveUserAgent(HttpServletRequest request) {
        if (request == null) {
            return null;
        }

        String userAgent = request.getHeader("User-Agent");
        if (userAgent == null || userAgent.isBlank()) {
            return null;
        }
        return userAgent.trim();
    }

    private String toJson(Map<String, Object> details) {
        if (details == null || details.isEmpty()) {
            return null;
        }

        try {
            return objectMapper.writeValueAsString(details);
        } catch (JsonProcessingException ex) {
            return "{\"serialization_error\":\"" + ex.getMessage() + "\"}";
        }
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
}
