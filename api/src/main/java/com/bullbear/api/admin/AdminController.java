package com.bullbear.api.admin;

import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** 관리자 화면 (/admin). 읽기 전용. 인증은 {@link AdminInterceptor} */
@RestController
@RequestMapping("/api/admin")
class AdminController {

	private final AdminService service;

	AdminController(AdminService service) {
		this.service = service;
	}

	@GetMapping("/overview")
	Map<String, Object> overview(@RequestParam(defaultValue = "14") int days) {
		return service.overview(Math.max(1, Math.min(days, 90)));
	}

	@GetMapping("/debates")
	List<Map<String, Object>> debates(@RequestParam(defaultValue = "50") int limit,
			@RequestParam(required = false) String status, @RequestParam(required = false) String origin) {
		return service.debates(Math.max(1, Math.min(limit, 500)), blank(status), blank(origin));
	}

	@GetMapping("/debates/{id}")
	Map<String, Object> debate(@PathVariable UUID id) {
		return service.debate(id);
	}

	private static String blank(String s) {
		return s == null || s.isBlank() ? null : s;
	}
}
