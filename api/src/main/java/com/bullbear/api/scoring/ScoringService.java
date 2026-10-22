package com.bullbear.api.scoring;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.function.Function;
import java.util.stream.Collectors;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import com.bullbear.api.common.ApiException;
import com.bullbear.api.config.BullbearProperties;
import com.bullbear.api.debate.Debate;
import com.bullbear.api.debate.DebateService;
import com.bullbear.api.debate.ModeratorVerdict;
import com.bullbear.api.debate.ModeratorVerdictRepository;
import com.bullbear.api.judgment.Judgment;
import com.bullbear.api.judgment.JudgmentRepository;
import com.bullbear.api.judgment.JudgmentService.JudgmentSubmitted;
import com.bullbear.api.worker.DailyClose;
import com.bullbear.api.worker.WorkerClient;

/**
 * 판정을 3·7거래일 뒤 실제 주가로 채점한다.
 *
 * 거래일 달력을 따로 두지 않는다. 판정 기준일(스냅샷 날짜) 이후 시세가 실제로 있는 날을 세어
 * N번째 날 종가로 채점하므로, 휴장일이 끼면 자연히 하루 밀린다.
 */
@Service
public class ScoringService {

	public static final int[] HORIZONS = { 3, 7 };
	private static final Logger log = LoggerFactory.getLogger(ScoringService.class);

	private final JudgmentScoreRepository scores;
	private final JudgmentRepository judgments;
	private final DebateService debates;
	private final ModeratorVerdictRepository verdicts;
	private final WorkerClient worker;
	private final Clock clock;
	private final BullbearProperties.Scoring config;

	ScoringService(JudgmentScoreRepository scores, JudgmentRepository judgments, DebateService debates,
			ModeratorVerdictRepository verdicts, WorkerClient worker, Clock clock, BullbearProperties properties) {
		this.scores = scores;
		this.judgments = judgments;
		this.debates = debates;
		this.verdicts = verdicts;
		this.worker = worker;
		this.clock = clock;
		this.config = properties.scoring();
	}

	/** 판정이 저장되면 채점 두 건(3·7거래일)을 예약한다. */
	@EventListener
	public void schedule(JudgmentSubmitted event) {
		if (scores.existsByJudgmentId(event.judgmentId())) {
			return;
		}
		LocalDate base = debates.get(event.debateId()).getTradeDate();
		for (int h : HORIZONS) {
			scores.save(JudgmentScore.pending(event.judgmentId(), h, ScoreRule.estimateTradingDay(base, h)));
		}
	}

	/** 장 마감 뒤 몇 번 돈다. 시세가 늦게 들어와도 다음 회차에 채점된다. */
	@Scheduled(cron = "${bullbear.scoring.cron}", zone = "Asia/Seoul")
	public void scheduled() {
		int n = scorePending();
		if (n > 0) {
			log.info("채점 {}건 완료", n);
		}
	}

	/** @return 이번에 채점한 건수 */
	public int scorePending() {
		List<JudgmentScore> pending = scores.findByStatus(JudgmentScore.Status.PENDING);
		if (pending.isEmpty()) {
			return 0;
		}
		Map<UUID, Judgment> judgmentById = byId(judgments.findAllById(pending.stream().map(JudgmentScore::getJudgmentId).toList()), Judgment::getId);
		var debateIds = judgmentById.values().stream().map(Judgment::getDebateId).distinct().toList();
		Map<UUID, Debate> debateById = byId(debates.getAll(debateIds), Debate::getId);
		Map<UUID, ModeratorVerdict> verdictById = byId(verdicts.findAllById(debateIds), ModeratorVerdict::getDebateId);

		// 같은 토론(같은 종목·같은 기준일)끼리 묶어 시세를 한 번만 받는다
		Map<UUID, List<JudgmentScore>> byDebate = pending.stream()
				.collect(Collectors.groupingBy(s -> judgmentById.get(s.getJudgmentId()).getDebateId()));
		LocalDate today = LocalDate.now(clock);
		int scored = 0;
		for (var entry : byDebate.entrySet()) {
			Debate debate = debateById.get(entry.getKey());
			try {
				scored += scoreDebate(debate, verdictById.get(debate.getId()), entry.getValue(), judgmentById, today);
			} catch (ApiException e) {
				log.warn("채점 보류 (시세 조회 실패): debate={} {}", debate.getId(), e.getMessage());
			}
		}
		return scored;
	}

	private int scoreDebate(Debate debate, ModeratorVerdict verdict, List<JudgmentScore> pending,
			Map<UUID, Judgment> judgmentById, LocalDate today) {
		LocalDate base = debate.getTradeDate();
		List<DailyClose> stock = worker.dailyCloses(debate.getTicker(), base, today);
		Map<LocalDate, BigDecimal> index = worker.indexCloses(config.index(), base, today).stream()
				.collect(Collectors.toMap(DailyClose::date, DailyClose::close));
		BigDecimal baseIndex = index.get(base);
		if (baseIndex == null) {
			log.warn("기준일 지수 없음: {} {}", config.index(), base);
			return 0;
		}
		List<DailyClose> after = new ArrayList<>(stock.stream().filter(c -> c.date().isAfter(base)).toList());

		int scored = 0;
		Instant now = clock.instant();
		for (JudgmentScore s : pending) {
			Optional<ScoreResult> result = compute(s.getHorizonDays(), after, index, debate.getBasePrice(), baseIndex,
					judgmentById.get(s.getJudgmentId()).getDecision().name(), verdict.getDecision());
			if (result.isPresent()) {
				s.complete(result.get(), now);
				scores.save(s);
				scored++;
			}
		}
		return scored;
	}

	private Optional<ScoreResult> compute(int horizon, List<DailyClose> after, Map<LocalDate, BigDecimal> index,
			BigDecimal basePrice, BigDecimal baseIndex, String userDecision, String moderatorDecision) {
		if (after.size() < horizon) {
			return Optional.empty(); // 아직 N거래일이 안 지났다
		}
		DailyClose day = after.get(horizon - 1);
		BigDecimal indexClose = index.get(day.date());
		if (indexClose == null) {
			return Optional.empty(); // 지수가 아직 안 들어왔다
		}
		BigDecimal stockRet = ScoreRule.returnPct(basePrice, day.close());
		BigDecimal indexRet = ScoreRule.returnPct(baseIndex, indexClose);
		BigDecimal excess = stockRet.subtract(indexRet);
		return Optional.of(new ScoreResult(day.date(), day.close(), indexClose, baseIndex, stockRet, indexRet, excess,
				ScoreRule.hit(userDecision, excess, config.holdBand()),
				ScoreRule.hit(moderatorDecision, excess, config.holdBand())));
	}

	private static <T> Map<UUID, T> byId(List<T> items, Function<T, UUID> id) {
		return items.stream().collect(Collectors.toMap(id, Function.identity()));
	}
}
