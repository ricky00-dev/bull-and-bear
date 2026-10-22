package com.bullbear.api.config;

import java.util.List;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import com.bullbear.api.auth.AuthInterceptor;
import com.bullbear.api.auth.CurrentUserArgumentResolver;

@Configuration
public class WebConfig implements WebMvcConfigurer {

	private final BullbearProperties properties;
	private final AuthInterceptor authInterceptor;

	public WebConfig(BullbearProperties properties, AuthInterceptor authInterceptor) {
		this.properties = properties;
		this.authInterceptor = authInterceptor;
	}

	@Override
	public void addCorsMappings(CorsRegistry registry) {
		// 웹과 Capacitor 앱은 출처가 다르다. 쿠키 없이 Authorization 헤더로 인증한다.
		registry.addMapping("/api/**")
				.allowedOrigins(properties.cors().allowedOrigins().toArray(String[]::new))
				.allowedMethods("GET", "POST", "PUT", "DELETE", "OPTIONS")
				.allowedHeaders("Authorization", "Content-Type", "Last-Event-ID");
	}

	@Override
	public void addInterceptors(InterceptorRegistry registry) {
		registry.addInterceptor(authInterceptor)
				.addPathPatterns("/api/**")
				.excludePathPatterns("/api/auth/guest");
	}

	@Override
	public void addArgumentResolvers(List<HandlerMethodArgumentResolver> resolvers) {
		resolvers.add(new CurrentUserArgumentResolver());
	}
}
