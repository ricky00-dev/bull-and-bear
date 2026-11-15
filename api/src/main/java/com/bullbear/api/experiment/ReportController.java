package com.bullbear.api.experiment;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** AI 성적표. 누구나 같은 숫자를 본다 */
@RestController
public class ReportController {

	private final ReportService reports;

	ReportController(ReportService reports) {
		this.reports = reports;
	}

	/** @param scope official(기본, 정식 운용만) | all(예비 운용 포함) */
	@GetMapping("/api/report")
	public ReportService.Report report(@RequestParam(defaultValue = "official") String scope) {
		return reports.report(!"all".equals(scope));
	}
}
