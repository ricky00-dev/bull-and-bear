package com.bullbear.api.me;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.function.Function;
import java.util.stream.Collectors;

import org.springframework.stereotype.Service;

import com.bullbear.api.common.ApiException;
import com.bullbear.api.common.ErrorCode;
import com.bullbear.api.config.BullbearProperties;
import com.bullbear.api.debate.Debate;
import com.bullbear.api.debate.DebateService;
import com.bullbear.api.debate.ModeratorVerdict;
import com.bullbear.api.debate.ModeratorVerdictRepository;
import com.bullbear.api.judgment.Decision;
import com.bullbear.api.judgment.Judgment;
import com.bullbear.api.judgment.JudgmentRepository;
import com.bullbear.api.scoring.JudgmentScore;
import com.bullbear.api.scoring.JudgmentScoreRepository;
import com.bullbear.api.user.User;

import tools.jackson.databind.ObjectMapper;

/** 내 판정 기록, 채점 결과, 판정 습관. */
@Service
public class MeService {

	/** 적중률은 7거래일 채점 기준 (판정 질문이 "7거래일 뒤"이므로) */
	static final int MAIN_HORIZON = 7;

	public record ScoreView(int horizonDays, JudgmentScore.Status status, LocalDate scheduledDate,
			LocalDate scoredTradeDate, BigDecimal stockReturn, BigDecimal indexReturn, BigDecimal excessReturn,
			Boolean userHit, Boolean moderatorHit) {

		static ScoreView of(JudgmentScore s) {
			return new ScoreView(s.getHorizonDays(), s.getStatus(), s.getScheduledDate(), s.getScoredTradeDate(),
					s.getStockReturn(), s.getIndexReturn(), s.getExcessReturn(), s.getUserHit(), s.getModeratorHit());
		}
	}

	public record JudgmentView(UUID judgmentId, UUID debateId, String ticker, String stockName, LocalDate tradeDate,
			BigDecimal basePrice, Decision decision, int confidence, String moderatorDecision, Instant createdAt,
			List<ScoreView> scores) {
	}

	/**
	 * @param pickResults 내가 고른 근거마다 인용한 쪽과 채점 결과 (가장 최근 채점 기준)
	 * @param pickHorizon pickResults를 채점한 거래일 수. 채점 전이면 null
	 */
	public record JudgmentDetail(JudgmentView judgment, List<String> evidencePicks, String memo,
			List<String> decisiveEvidence, BigDecimal holdBand, List<EvidenceGrader.Pick> pickResults,
			Integer pickHorizon) {
	}

	/**
	 * @param right  7거래일 채점에서 이 분류 근거가 맞은 방향이었던 횟수
	 * @param graded 맞았거나 틀린 횟수 (코스피와 비슷해 판가름 안 난 경우·채점 전은 뺀다)
	 */
	public record HabitSlice(String category, String label, long count, long right, long graded) {
	}

	/**
	 * @param scored 7거래일 채점이 끝난 판정 수
	 * @param beatAi 내가 맞히고 AI가 틀린 판정 수
	 */
	public record Stats(long judged, long scored, long userHits, long moderatorHits, long beatAi,
			BigDecimal userHitRate, BigDecimal moderatorHitRate, List<HabitSlice> evidenceHabit) {
	}

	private final JudgmentRepository judgments;
	private final JudgmentScoreRepository scores;
	private final DebateService debates;
	private final ModeratorVerdictRepository verdicts;
	private final ObjectMapper json;
	private final BigDecimal holdBand;

	MeService(JudgmentRepository judgments, JudgmentScoreRepository scores, DebateService debates,
			ModeratorVerdictRepository verdicts, ObjectMapper json, BullbearProperties properties) {
		this.judgments = judgments;
		this.scores = scores;
		this.debates = debates;
		this.verdicts = verdicts;
		this.json = json;
		this.holdBand = properties.scoring().holdBand();
	}

	public List<JudgmentView> list(User user) {
		return views(judgments.findByUserIdOrderByCreatedAtDesc(user.getId()));
	}

	public JudgmentDetail detail(User user, UUID judgmentId) {
		Judgment j = judgments.findById(judgmentId)
				.filter(x -> x.getUserId().equals(user.getId()))
				.orElseThrow(() -> new ApiException(ErrorCode.NOT_FOUND, "판정을 찾을 수 없습니다"));
		JudgmentView view = views(List.of(j)).get(0);
		List<String> decisive = verdicts.findById(j.getDebateId())
				.map(v -> {
					List<String> ids = new ArrayList<>();
					json.readTree(v.getPayload()).path("decisive_evidence").forEach(n -> ids.add(n.asString()));
					return ids;
				})
				.orElse(List.of());
		var latest = view.scores().stream()
				.filter(x -> x.status() == JudgmentScore.Status.SCORED)
				.max(Comparator.comparingInt(ScoreView::horizonDays));
		List<EvidenceGrader.Pick> picks = EvidenceGrader.grade(j.getEvidencePicks(), sides(j.getDebateId()),
				latest.map(ScoreView::excessReturn).orElse(null), holdBand);
		return new JudgmentDetail(view, j.getEvidencePicks(), j.getMemo(), decisive, holdBand, picks,
				latest.map(ScoreView::horizonDays).orElse(null));
	}

	public Stats stats(User user) {
		List<Judgment> mine = judgments.findByUserIdOrderByCreatedAtDesc(user.getId());
		List<JudgmentScore> finals = scores.findByJudgmentIdIn(mine.stream().map(Judgment::getId).toList()).stream()
				.filter(s -> s.getHorizonDays() == MAIN_HORIZON && s.getStatus() == JudgmentScore.Status.SCORED)
				.toList();
		long userHits = finals.stream().filter(s -> Boolean.TRUE.equals(s.getUserHit())).count();
		long modHits = finals.stream().filter(s -> Boolean.TRUE.equals(s.getModeratorHit())).count();
		long beatAi = finals.stream()
				.filter(s -> Boolean.TRUE.equals(s.getUserHit()) && Boolean.FALSE.equals(s.getModeratorHit())).count();

		Map<EvidenceCategory, Long> habit = mine.stream()
				.flatMap(j -> j.getEvidencePicks().stream())
				.collect(Collectors.groupingBy(EvidenceCategory::of, () -> new LinkedHashMap<>(), Collectors.counting()));

		// 분류별 근거 적중: 7거래일 채점이 끝난 판정의 근거만 센다
		Map<UUID, BigDecimal> excessByJudgment = finals.stream()
				.collect(Collectors.toMap(JudgmentScore::getJudgmentId, JudgmentScore::getExcessReturn));
		Map<EvidenceCategory, long[]> grades = new LinkedHashMap<>();
		for (Judgment j : mine) {
			BigDecimal excess = excessByJudgment.get(j.getId());
			if (excess == null || j.getEvidencePicks().isEmpty()) {
				continue;
			}
			for (var p : EvidenceGrader.grade(j.getEvidencePicks(), sides(j.getDebateId()), excess, holdBand)) {
				long[] g = grades.computeIfAbsent(EvidenceCategory.of(p.sourceId()), k -> new long[2]);
				if (p.result() == EvidenceGrader.Result.RIGHT) g[0]++;
				if (p.result() == EvidenceGrader.Result.RIGHT || p.result() == EvidenceGrader.Result.WRONG) g[1]++;
			}
		}
		List<HabitSlice> slices = habit.entrySet().stream()
				.sorted(Map.Entry.<EvidenceCategory, Long>comparingByValue().reversed())
				.map(e -> {
					long[] g = grades.getOrDefault(e.getKey(), new long[2]);
					return new HabitSlice(e.getKey().name().toLowerCase(), e.getKey().label, e.getValue(), g[0], g[1]);
				})
				.toList();
		return new Stats(mine.size(), finals.size(), userHits, modHits, beatAi, rate(userHits, finals.size()),
				rate(modHits, finals.size()), slices);
	}

	private List<JudgmentView> views(List<Judgment> list) {
		if (list.isEmpty()) {
			return List.of();
		}
		var debateIds = list.stream().map(Judgment::getDebateId).distinct().toList();
		Map<UUID, Debate> debateById = debates.getAll(debateIds).stream()
				.collect(Collectors.toMap(Debate::getId, Function.identity()));
		Map<UUID, String> verdictById = verdicts.findAllById(debateIds).stream()
				.collect(Collectors.toMap(ModeratorVerdict::getDebateId, ModeratorVerdict::getDecision));
		Map<UUID, List<JudgmentScore>> scoresByJudgment = scores
				.findByJudgmentIdIn(list.stream().map(Judgment::getId).toList()).stream()
				.collect(Collectors.groupingBy(JudgmentScore::getJudgmentId));
		return list.stream().map(j -> {
			Debate d = debateById.get(j.getDebateId());
			List<ScoreView> sv = scoresByJudgment.getOrDefault(j.getId(), List.of()).stream()
					.sorted(Comparator.comparingInt(JudgmentScore::getHorizonDays)).map(ScoreView::of).toList();
			return new JudgmentView(j.getId(), d.getId(), d.getTicker(), d.getStockName(), d.getTradeDate(),
					d.getBasePrice(), j.getDecision(), j.getConfidence(), verdictById.get(d.getId()), j.getCreatedAt(), sv);
		}).toList();
	}

	private Map<String, Set<String>> sides(UUID debateId) {
		return EvidenceGrader.sidesBySource(debates.acceptedStatements(debateId), json);
	}

	private static BigDecimal rate(long hits, long total) {
		return total == 0 ? null : BigDecimal.valueOf(hits * 100).divide(BigDecimal.valueOf(total), 1, RoundingMode.HALF_UP);
	}

	/** 근거 ID → 습관 리포트 분류 */
	enum EvidenceCategory {
		TREND("추세"), VOLUME("거래량"), VOLATILITY("변동성"), VALUATION("밸류에이션"), FINANCIALS("재무"),
		NEWS("뉴스"), DISCLOSURE("공시"), OTHER("기타");

		final String label;

		EvidenceCategory(String label) {
			this.label = label;
		}

		static EvidenceCategory of(String sourceId) {
			if (sourceId.equals("PX.VOL_20D")) return VOLATILITY;
			if (sourceId.startsWith("PX.VOLUME") || sourceId.startsWith("PX.AVG_VOLUME")) return VOLUME;
			if (sourceId.startsWith("PX.")) return TREND;
			if (sourceId.startsWith("VAL.")) return VALUATION;
			if (sourceId.startsWith("FIN.")) return FINANCIALS;
			if (sourceId.startsWith("NEWS.")) return NEWS;
			if (sourceId.startsWith("DISC.")) return DISCLOSURE;
			return OTHER;
		}
	}
}
