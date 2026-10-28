package com.bullbear.api.chart;

import java.util.UUID;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

import com.bullbear.api.debate.DebateService;

/** 판정일 전후 주가 차트 (구성은 {@link ChartService}). */
@RestController
public class ChartController {

	private final DebateService debates;
	private final ChartService charts;

	public ChartController(DebateService debates, ChartService charts) {
		this.debates = debates;
		this.charts = charts;
	}

	@GetMapping("/api/debates/{id}/chart")
	public ChartService.ChartResponse chart(@PathVariable UUID id) {
		return charts.build(debates.get(id));
	}
}
