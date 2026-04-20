package com.egx.core.config;

import com.egx.core.security.JwtAuthFilter;
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
import java.util.stream.Collectors;

@Configuration
@EnableWebSecurity
public class SecurityConfig {

    private final boolean requireAuth;
    private final String allowedOriginPatterns;
    private final JwtAuthFilter jwtAuthFilter;

    public SecurityConfig(
            @Value("${app.security.require-auth:true}") boolean requireAuth,
            @Value("${app.security.allowed-origin-patterns:http://localhost:3000,http://localhost:5173,http://localhost:8080}")
            String allowedOriginPatterns,
            JwtAuthFilter jwtAuthFilter
    ) {
        this.requireAuth = requireAuth;
        this.allowedOriginPatterns = allowedOriginPatterns;
        this.jwtAuthFilter = jwtAuthFilter;
    }

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http
                .csrf(AbstractHttpConfigurer::disable)
                .cors(cors -> cors.configurationSource(corsConfigurationSource()))
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .httpBasic(AbstractHttpConfigurer::disable)
                .formLogin(AbstractHttpConfigurer::disable)
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

                    // Protect all gateway-routed core APIs.
                    auth.requestMatchers("/api/core/**").authenticated();

                    if (requireAuth) {
                        auth.anyRequest().authenticated();
                    } else {
                        auth.anyRequest().permitAll();
                    }
                })
                .addFilterBefore(jwtAuthFilter, UsernamePasswordAuthenticationFilter.class);

        return http.build();
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    public CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration cors = new CorsConfiguration();
        cors.setAllowedOriginPatterns(parseAllowedOrigins(allowedOriginPatterns));
        cors.setAllowedMethods(List.of("GET", "POST", "PUT", "DELETE", "OPTIONS"));
        cors.setAllowedHeaders(List.of("Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"));
        cors.setExposedHeaders(List.of("Authorization"));
        cors.setAllowCredentials(false);
        cors.setMaxAge(3600L);

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", cors);
        return source;
    }

    private List<String> parseAllowedOrigins(String csv) {
        return Arrays.stream(csv.split(","))
                .map(String::trim)
                .filter(value -> !value.isBlank())
                .collect(Collectors.toList());
    }
}
