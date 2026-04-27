package com.egx.core.config;

import java.util.Arrays;
import java.util.List;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
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

import com.egx.core.security.AuthRateLimitFilter;
import com.egx.core.security.JwtAuthFilter;
import com.egx.core.security.SecurityRateLimitingFilter;

@Configuration
@EnableWebSecurity
@EnableMethodSecurity(prePostEnabled = true)
public class SecurityConfig {

    private final boolean forceHttps;
    private final String corsAllowedOrigins;
    private final JwtAuthFilter jwtAuthFilter;
    private final AuthRateLimitFilter authRateLimitFilter;
    private final SecurityRateLimitingFilter securityRateLimitingFilter;
    private final Environment environment;

    public SecurityConfig(
            @Value("${app.security.force-https:false}") boolean forceHttps,
            @Value("${app.security.cors.allowed-origins:http://localhost:5173}") String corsAllowedOrigins,
            JwtAuthFilter jwtAuthFilter,
            AuthRateLimitFilter authRateLimitFilter,
            SecurityRateLimitingFilter securityRateLimitingFilter,
            Environment environment
    ) {
        this.forceHttps = forceHttps;
        this.corsAllowedOrigins = corsAllowedOrigins;
        this.jwtAuthFilter = jwtAuthFilter;
        this.authRateLimitFilter = authRateLimitFilter;
        this.securityRateLimitingFilter = securityRateLimitingFilter;
        this.environment = environment;
    }

    /**
     * Determines if authentication is required based on active Spring profile.
     * Auth bypass is STRICTLY limited to 'dev' profile only.
     * Production environments MUST enforce JWT authentication.
     */
    private boolean isAuthRequired() {
        List<String> activeProfiles = Arrays.asList(environment.getActiveProfiles());
        // Only allow auth bypass in dev profile
        return !activeProfiles.contains("dev");
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
                        .contentTypeOptions(contentTypeOptions -> {
                        })
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
                    auth.requestMatchers(
                            "/instruments",
                            "/instruments/catalog",
                            "/instruments/ids",
                            "/api/core/instruments",
                            "/api/core/instruments/catalog",
                            "/api/core/instruments/ids"
                    ).permitAll();
                    auth.requestMatchers("/market-data/bulk", "/api/core/market-data/bulk").permitAll();
                    auth.requestMatchers("/model-performance/**", "/api/core/model-performance/**").permitAll();

                    // Auth endpoints stay open by design.
                    auth.requestMatchers("/auth/**", "/api/core/auth/**").permitAll();

                    // User profile and session endpoints must always be authenticated.
                    auth.requestMatchers("/users/**", "/api/core/users/**").authenticated();

                    // Premium-only API surface (PRO and ADMIN roles).
                    auth.requestMatchers(
                            "/premium/**",
                            "/api/core/premium/**",
                            "/ai/performance-summary",
                            "/api/core/ai/performance-summary"
                    ).hasAnyRole("PRO", "ADMIN");

                    // Admin-only API surface.
                    auth.requestMatchers("/admin/**", "/api/core/admin/**").hasRole("ADMIN");

                    // Protect all gateway-routed core APIs.
                    auth.requestMatchers("/api/core/**").authenticated();

                    if (isAuthRequired()) {
                        auth.anyRequest().authenticated();
                    } else {
                        // Dev profile only: allow all requests for local testing
                        auth.anyRequest().permitAll();
                    }
                })
                // Keep the custom filters in front of UsernamePasswordAuthenticationFilter.
                // Using a custom filter class as an anchor can fail in recent Spring Security versions
                // if that class has no pre-registered order.
                .addFilterBefore(securityRateLimitingFilter, UsernamePasswordAuthenticationFilter.class)
                .addFilterBefore(authRateLimitFilter, UsernamePasswordAuthenticationFilter.class)
                .addFilterBefore(jwtAuthFilter, org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter.class);

        return http.build();
    }

    @Bean
    public FilterRegistrationBean<JwtAuthFilter> jwtAuthFilterRegistration(JwtAuthFilter filter) {
        FilterRegistrationBean<JwtAuthFilter> registration = new FilterRegistrationBean<>(filter);
        registration.setEnabled(false);
        return registration;
    }

    @Bean
    public FilterRegistrationBean<AuthRateLimitFilter> authRateLimitFilterRegistration(AuthRateLimitFilter filter) {
        FilterRegistrationBean<AuthRateLimitFilter> registration = new FilterRegistrationBean<>(filter);
        registration.setEnabled(false);
        return registration;
    }

    @Bean
    public FilterRegistrationBean<SecurityRateLimitingFilter> securityRateLimitingFilterRegistration(
            SecurityRateLimitingFilter filter
    ) {
        FilterRegistrationBean<SecurityRateLimitingFilter> registration = new FilterRegistrationBean<>(filter);
        registration.setEnabled(false);
        return registration;
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder(12);
    }

    @Bean
    public CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration cors = new CorsConfiguration();

        // P2 Fix: Strict origin validation - never allow wildcard in production
        List<String> origins = Arrays.asList(corsAllowedOrigins.split(","));
        cors.setAllowedOrigins(origins);

        cors.setAllowedMethods(List.of("GET", "POST", "PUT", "DELETE", "OPTIONS"));
        cors.setAllowedHeaders(List.of(
                "Authorization",
                "Content-Type",
                "Accept",
                "Origin",
                "X-Requested-With",
                "X-Session-Id"
        ));
        cors.setExposedHeaders(List.of("Authorization", "X-Session-Id"));
        cors.setAllowCredentials(true);
        cors.setMaxAge(3600L);

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", cors);
        return source;
    }
}
