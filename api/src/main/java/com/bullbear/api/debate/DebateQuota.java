package com.bullbear.api.debate;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.LocalDate;
import java.util.UUID;

import org.springframework.stereotype.Component;

import com.bullbear.api.common.ApiException;
import com.bullbear.api.common.ErrorCode;
import com.bullbear.api.config.BullbearProperties;

/**
 * 새 토론을 시작해도 되는지 본다. 오늘 이미 있는 토론을 재사용하는 건 막지 않는다 (비용이 들지 않으므로).
 *
 * 동시에 여러 요청이 오면 상한을 토론 한두 건만큼 넘을 수 있다. 하루 상한이 넉넉해서 잠그지 않는다.
 */
@Component
public class DebateQuota {

	/**
	 * @param left 오늘 이 사용자가 더 시작할 수 있는 새 토론 수
	 * @param budgetOpen 오늘 전체 비용 상한이 남았는지. false면 오늘 토론만 볼 수 있다
	 */
	public record Status(int left, int limit, boolean budgetOpen) {
	}

	private final DebateRepository debates;
	private final BullbearProperties.Budget budget;
	private final Clock clock;

	DebateQuota(DebateRepository debates, BullbearProperties properties, Clock clock) {
		this.debates = debates;
		this.budget = properties.budget();
		this.clock = clock;
	}

	public Status status(UUID userId) {
		LocalDate today = LocalDate.now(clock);
		int used = (int) debates.countStartedBy(userId, today);
		return new Status(Math.max(0, budget.perUserDailyDebates() - used), budget.perUserDailyDebates(),
				spentToday(today).add(budget.estimateUsd()).compareTo(budget.userDailyUsd()) <= 0);
	}

	void check(UUID userId) {
		Status s = status(userId);
		if (!s.budgetOpen()) {
			throw new ApiException(ErrorCode.BUDGET_EXHAUSTED, "오늘 준비한 AI 토론이 모두 소진됐어요. 오늘 진행된 토론은 볼 수 있어요.");
		}
		if (s.left() == 0) {
			throw new ApiException(ErrorCode.DAILY_LIMIT,
					"새 토론은 하루 " + s.limit() + "번까지 시작할 수 있어요. 오늘 진행된 다른 종목 토론은 볼 수 있어요.");
		}
	}

	/** 전향 운용(스케줄러) 토론을 하나 더 돌려도 되는지. 사용자 상한과 따로 센다. */
	public boolean scheduledBudgetOpen(BigDecimal dailyUsd) {
		BigDecimal spent = debates.costOn(LocalDate.now(clock), Debate.Origin.SCHEDULED, budget.estimateUsd());
		return spent.add(budget.estimateUsd()).compareTo(dailyUsd) <= 0;
	}

	/** 오늘 사용자 토론에 쓴 비용. 사용량을 아직 모르는 토론은 추정치로 센다. */
	BigDecimal spentToday(LocalDate today) {
		return debates.costOn(today, Debate.Origin.USER, budget.estimateUsd());
	}
}
