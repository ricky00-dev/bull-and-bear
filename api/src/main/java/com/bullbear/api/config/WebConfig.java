package com.bullbear.api.config;

import java.util.List;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import com.bullbear.api.admin.AdminInterceptor;
import com.bullbear.api.auth.AuthInterceptor;
import com.bullbear.api.auth.CurrentUserArgumentResolver;

@Configuration
public class WebConfig implements WebMvcConfigurer {

	private final BullbearProperties properties;
	private final AuthInterceptor authInterceptor;
	private final AdminInterceptor adminInterceptor;

	public WebConfig(BullbearProperties properties, AuthInterceptor authInterceptor, AdminInterceptor adminInterceptor) {
		this.properties = properties;
		this.authInterceptor = authInterceptor;
		this.adminInterceptor = adminInterceptor;
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
				.excludePathPatterns("/api/auth/guest", "/api/admin/**");
		// 관리자 화면은 사용자 토큰이 아니라 관리자 토큰으로 연다
		registry.addInterceptor(adminInterceptor).addPathPatterns("/api/admin/**");
	}

	@Override
	public void addArgumentResolvers(List<HandlerMethodArgumentResolver> resolvers) {
		resolvers.add(new CurrentUserArgumentResolver());
	}
}
