package com.egx.core.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import com.egx.core.repository.TokenBlacklistRepository;
import com.egx.core.repository.UserRepository;
import com.egx.core.repository.UserSessionRepository;
import com.egx.core.security.AuthCookieService;
import com.egx.core.security.JwtAuthFilter;
import com.egx.core.security.JwtService;

@Configuration
public class SecurityFilterBeansConfig {

    @Bean
    public JwtAuthFilter jwtAuthFilter(
            JwtService jwtService,
            TokenBlacklistRepository tokenBlacklistRepository,
            UserRepository userRepository,
            UserSessionRepository userSessionRepository,
            AuthCookieService authCookieService
    ) {
        return new JwtAuthFilter(
                jwtService,
                tokenBlacklistRepository,
                userRepository,
                userSessionRepository,
                authCookieService
        );
    }
}
