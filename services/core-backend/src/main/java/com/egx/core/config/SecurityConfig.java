package com.egx.core.config;

import com.egx.core.security.JwtAuthFilter;
import com.egx.core.security.SecurityRateLimitingFilter;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.stream.Collectors;

@Configuration
@EnableWebSecurity
public class SecurityConfig {

    private final boolean requireAuth;
    private final boolean productionMode;
    private final boolean forceHttps;
    private final String allowedOrigins;
    private final JwtAuthFilter jwtAuthFilter;
    private final SecurityRateLimitingFilter securityRateLimitingFilter;

    public SecurityConfig(
            @Value("${app.security.require-auth:true}") boolean requireAuth,
            @Value("${app.security.production-mode:false}") boolean productionMode,
            @Value("${app.security.force-https:false}") boolean forceHttps,
            @Value("${app.security.allowed-origins:http://localhost:3000,http://localhost:5173,http://localhost:8080}")
            String allowedOrigins,
            JwtAuthFilter jwtAuthFilter,
            SecurityRateLimitingFilter securityRateLimitingFilter
    ) {
        this.requireAuth = requireAuth;
        this.productionMode = productionMode;
        this.forceHttps = forceHttps;
        this.allowedOrigins = allowedOrigins;
        this.jwtAuthFilter = jwtAuthFilter;
        this.securityRateLimitingFilter = securityRateLimitingFilter;
    }

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        if (forceHttps) {
            http.requiresChannel(channel -> channel.anyRequest().requiresSecure());
        }

        http
                .csrf(AbstractHttpConfigurer::disable)
                .cors(cors -> cors.configurationSource(corsConfigurationSource()))
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .httpBasic(AbstractHttpConfigurer::disable)
                .formLogin(AbstractHttpConfigurer::disable)
                .headers(headers -> headers
                        .contentTypeOptions(contentTypeOptions -> {})
                        .frameOptions(frameOptions -> frameOptions.deny())
                        .contentSecurityPolicy(csp -> csp.policyDirectives(
                                "default-src 'self'; "
                                        + "frame-ancestors 'none'; "
                                        + "object-src 'none'; "
                                        + "script-src 'self'; "
                                        + "style-src 'self' 'unsafe-inline'; "
                                        + "img-src 'self' data:; "
                                        + "connect-src 'self'"
                        ))
                )
                .authorizeHttpRequests(auth -> {
                    auth.requestMatchers(HttpMethod.OPTIONS, "/**").permitAll();
                    auth.requestMatchers("/swagger-ui/**", "/v3/api-docs/**", "/v3/api-docs.yaml").permitAll();
                    auth.requestMatchers("/actuator/health", "/actuator/info").permitAll();
                    auth.requestMatchers("/error").permitAll();
                    auth.requestMatchers("/instruments/bulk", "/api/core/instruments/bulk").permitAll();
                    auth.requestMatchers("/market-data/bulk", "/api/core/market-data/bulk").permitAll();
                    auth.requestMatchers("/model-performance/**", "/api/core/model-performance/**").permitAll();

                    // Auth endpoints stay open by design.
                    auth.requestMatchers("/auth/**", "/api/core/auth/**").permitAll();

                    // User profile and session endpoints must always be authenticated.
                    auth.requestMatchers("/users/**", "/api/core/users/**").authenticated();

            // Premium-only API surface.
            auth.requestMatchers(
                "/premium/**",
                "/api/core/premium/**",
                "/ai/performance-summary",
                "/api/core/ai/performance-summary"
            ).hasRole("PREMIUM");

                    // Protect all gateway-routed core APIs.
                    auth.requestMatchers("/api/core/**").authenticated();

                    if (requireAuth) {
                        auth.anyRequest().authenticated();
                    } else {
                        auth.anyRequest().permitAll();
                    }
                })
                .addFilterBefore(securityRateLimitingFilter, JwtAuthFilter.class)
                .addFilterBefore(jwtAuthFilter, UsernamePasswordAuthenticationFilter.class);

        return http.build();
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder(12);
    }

    @Bean
    public CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration cors = new CorsConfiguration();
        cors.setAllowedOrigins(parseAllowedOrigins(allowedOrigins));
        cors.setAllowedMethods(List.of("GET", "POST", "PUT", "DELETE", "OPTIONS"));
        cors.setAllowedHeaders(List.of(
                "Authorization",
                "Content-Type",
                "Accept",
                "Origin",
                "X-Requested-With",
                "X-Session-Id"
        ));
        cors.setExposedHeaders(List.of("X-Session-Id"));
        cors.setAllowCredentials(true);
        cors.setMaxAge(3600L);

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", cors);
        return source;
    }

    private List<String> parseAllowedOrigins(String csv) {
        List<String> parsed = Arrays.stream(csv.split(","))
                .map(String::trim)
                .filter(value -> !value.isBlank())
                .collect(Collectors.toList());

        if (productionMode && parsed.stream().anyMatch(origin -> origin.contains("*"))) {
            throw new IllegalStateException("Wildcard CORS origins are forbidden when production mode is enabled");
        }

        return parsed.stream()
                .map(value -> value.toLowerCase(Locale.ROOT))
                .toList();
    }
}
