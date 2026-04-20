package com.egx.core.service;

import com.egx.core.domain.SecurityAuditLog;
import com.egx.core.repository.SecurityAuditLogRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.Map;

@Service
public class SecurityAuditService {

    private static final Logger LOGGER = LoggerFactory.getLogger(SecurityAuditService.class);

    private final SecurityAuditLogRepository securityAuditLogRepository;
    private final ObjectMapper objectMapper;

    public SecurityAuditService(
            SecurityAuditLogRepository securityAuditLogRepository,
            ObjectMapper objectMapper
    ) {
        this.securityAuditLogRepository = securityAuditLogRepository;
        this.objectMapper = objectMapper;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void log(String action, Long userId, String outcome, Map<String, Object> details) {
        try {
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
        } catch (Exception ex) {
            LOGGER.warn("Security audit log persistence failed for action={} userId={}", action, userId, ex);
        }
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
        } catch (Exception ex) {
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
