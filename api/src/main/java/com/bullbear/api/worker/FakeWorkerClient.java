package com.bullbear.api.worker;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Clock;
import java.time.DayOfWeek;
import java.time.Duration;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.SplittableRandom;
import java.util.UUID;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import com.bullbear.api.common.ApiException;
import com.bullbear.api.common.ErrorCode;
import com.bullbear.api.config.BullbearProperties;

import reactor.core.publisher.Flux;
import tools.jackson.databind.ObjectMapper;

/**
 * 계약 문서(docs/worker-api.md)의 예시를 재생하는 가짜 워커.
 * Python 워커 없이 API·웹을 개발하기 위한 것이다. 시세는 2026-10-22 실제 종가.
 * 토론 내용은 종목과 무관하게 삼성전자 예시를 쓴다.
 */
@Component
@ConditionalOnProperty(name = "bullbear.worker.mode", havingValue = "fake", matchIfMissing = true)
public class FakeWorkerClient implements WorkerClient {

	private static final LocalDate AS_OF = LocalDate.of(2026, 10, 22);

	private static final List<WorkerStock> STOCKS = List.of(
			stock("005930", "삼성전자", "KOSPI", true, 214500, -4.03, null),
			stock("000660", "SK하이닉스", "KOSPI", true, 1234000, -4.19, null),
			stock("009150", "삼성전기", "KOSPI", false, 1146000, -3.21, null),
			stock("006400", "삼성SDI", "KOSPI", true, 515000, -7.54, null),
			stock("207940", "삼성바이오로직스", "KOSPI", true, 1361000, -3.61, null),
			stock("028260", "삼성물산", "KOSPI", true, 287500, -0.35, null),
			stock("032830", "삼성생명", "KOSPI", true, 240500, -0.62, null),
			stock("018260", "삼성에스디에스", "KOSPI", true, 209000, 4.50, null),
			stock("005935", "삼성전자우", "KOSPI", false, 166600, -3.36, "우선주는 토론하지 않아요"),
			stock("069500", "KODEX 200", "ETF", false, 86525, -3.57, "ETF는 토론하지 않아요"),
			stock("005380", "현대차", "KOSPI", true, 300500, -3.06, null),
			stock("035420", "NAVER", "KOSPI", true, 175500, -2.12, null),
			stock("035720", "카카오", "KOSPI", true, 30200, -2.42, null),
			stock("247540", "에코프로비엠", "KOSDAQ", false, 98800, -8.43, null));

	private static final List<Long> SAMSUNG_60D = List.of(249500L, 254000L, 220000L, 208500L, 207000L, 262500L,
			239500L, 240000L, 246000L, 230500L, 231000L, 230000L, 239500L, 255500L, 268000L, 274500L, 268500L,
			247500L, 271000L, 281500L, 257000L, 257000L, 261500L, 266000L, 257000L, 260000L, 261000L, 250500L,
			250000L, 255500L, 270000L, 269500L, 269500L, 269000L, 259500L, 248500L, 250500L, 253500L, 256000L,
			260000L, 275000L, 277500L, 286500L, 270000L, 275000L, 269500L, 274500L, 276000L, 273000L, 269000L,
			263000L, 251000L, 234000L, 234500L, 207500L, 217000L, 223500L, 209000L, 223500L, 214500L);

	/** 2026-10-22 실제 코스피 종가 */
	private static final BigDecimal KOSPI_AS_OF = new BigDecimal("5533.77");

	private final ObjectMapper json;
	private final Duration delay;
	private final Clock clock;

	public FakeWorkerClient(ObjectMapper json, BullbearProperties properties, Clock clock) {
		this.json = json;
		this.clock = clock;
		this.delay = properties.worker().fakeDelay() == null ? Duration.ZERO : properties.worker().fakeDelay();
	}

	@Override
	public List<WorkerStock> search(String query, int limit) {
		String q = query.trim();
		if (q.isEmpty()) {
			return List.of();
		}
		return STOCKS.stream()
				.filter(s -> s.name().contains(q) || s.ticker().startsWith(q) || Choseong.of(s.name()).contains(q))
				.limit(limit)
				.toList();
	}

	@Override
	public WorkerStockDetail stock(String ticker) {
		WorkerStock s = find(ticker);
		List<String> reasons = s.eligible() ? List.of() : List.of(s.blockReason());
		List<Long> spark = ticker.equals("005930") ? SAMSUNG_60D : last60(ticker, s.close());
		return new WorkerStockDetail(s.ticker(), s.name(), s.market(), s.close(), s.changePct(), AS_OF, s.eligible(),
				reasons, spark);
	}

	@Override
	public WorkerDebateStarted startDebate(String ticker, String requestId) {
		WorkerStock s = find(ticker);
		if (!s.eligible()) {
			throw new ApiException(ErrorCode.NOT_ELIGIBLE, s.blockReason());
		}
		String id = "fake-" + ticker + "-" + UUID.randomUUID().toString().substring(0, 8);
		return new WorkerDebateStarted(id, snapshotId(ticker), "running", false);
	}

	@Override
	public WorkerDebateStarted startSingle(String ticker, String snapshotId, String requestId) {
		find(ticker);
		return new WorkerDebateStarted("fakesingle-" + ticker + "-" + UUID.randomUUID().toString().substring(0, 8),
				snapshotId, "running", false);
	}

	/**
	 * 10/22 실제 종가를 기준으로 평일마다 결정적으로(같은 입력 → 같은 값) 움직이는 가짜 시세.
	 * 10/22 이전은 거꾸로 되짚어 만든다 (차트용). 오늘(시계) 이후 날짜는 만들지 않는다.
	 */
	@Override
	public List<DailyClose> dailyCloses(String ticker, LocalDate from, LocalDate to) {
		return series(ticker, BigDecimal.valueOf(find(ticker).close()), 300, from, to);
	}

	@Override
	public List<DailyClose> indexCloses(String code, LocalDate from, LocalDate to) {
		return series(code, KOSPI_AS_OF, 150, from, to);
	}

	/** @param maxBp 하루 최대 등락 (bp, 300 = ±3%) */
	private List<DailyClose> series(String key, BigDecimal start, int maxBp, LocalDate from, LocalDate to) {
		LocalDate today = LocalDate.now(clock);
		LocalDate end = to.isAfter(today) ? today : to;
		List<DailyClose> out = new ArrayList<>();
		// 10/22 이전: 그날 등락을 되돌리며 과거로
		BigDecimal price = start;
		for (LocalDate d = AS_OF.minusDays(1); !d.isBefore(from); d = d.minusDays(1)) {
			if (!weekend(d)) {
				price = price.divide(BigDecimal.ONE.add(move(key, nextWeekday(d), maxBp)), 2, RoundingMode.HALF_UP);
				out.add(0, new DailyClose(d, price));
			}
		}
		price = start;
		for (LocalDate d = AS_OF; !d.isAfter(end); d = d.plusDays(1)) {
			if (weekend(d)) {
				continue;
			}
			if (d.isAfter(AS_OF)) {
				price = price.multiply(BigDecimal.ONE.add(move(key, d, maxBp))).setScale(2, RoundingMode.HALF_UP);
			}
			if (!d.isBefore(from)) {
				out.add(new DailyClose(d, price));
			}
		}
		return out;
	}

	private List<Long> last60(String ticker, long close) {
		List<DailyClose> all = series(ticker, BigDecimal.valueOf(close), 300, AS_OF.minusDays(100), AS_OF);
		return all.subList(Math.max(0, all.size() - 60), all.size()).stream().map(c -> c.close().longValue()).toList();
	}

	/** 그날 등락률 (소수, ±maxBp bp) */
	private static BigDecimal move(String key, LocalDate d, int maxBp) {
		// 문자열 해시는 연속한 날짜끼리 값이 비슷해 시세가 직선이 된다. 섞어서 쓴다.
		int bp = new SplittableRandom((key + d).hashCode()).nextInt(2 * maxBp + 1) - maxBp;
		return BigDecimal.valueOf(bp, 4);
	}

	private static boolean weekend(LocalDate d) {
		return d.getDayOfWeek() == DayOfWeek.SATURDAY || d.getDayOfWeek() == DayOfWeek.SUNDAY;
	}

	private static LocalDate nextWeekday(LocalDate d) {
		LocalDate n = d.plusDays(1);
		while (weekend(n)) {
			n = n.plusDays(1);
		}
		return n;
	}

	@Override
	public Flux<WorkerEvent> events(String workerDebateId, long afterSeq) {
		String ticker = workerDebateId.split("-")[1];
		List<WorkerEvent> script = workerDebateId.startsWith("fakesingle-") ? single(find(ticker))
				: script(workerDebateId, find(ticker));
		Flux<WorkerEvent> events = Flux.fromIterable(script)
				.filter(e -> e.seq() > afterSeq);
		return delay.isZero() ? events : events.delayElements(delay);
	}

	private WorkerStock find(String ticker) {
		return STOCKS.stream().filter(s -> s.ticker().equals(ticker)).findFirst()
				.orElseThrow(() -> new ApiException(ErrorCode.NOT_FOUND, "종목을 찾을 수 없습니다: " + ticker));
	}

	private static String snapshotId(String ticker) {
		return ticker + "-20261022-fake";
	}

	private static WorkerStock stock(String ticker, String name, String market, boolean featured, long close,
			double change, String blockReason) {
		return new WorkerStock(ticker, name, market, featured, close, change, blockReason == null, blockReason);
	}

	// ---- 토론 대본 ----

	private List<WorkerEvent> script(String workerDebateId, WorkerStock s) {
		List<Map<String, Object>> raw = new ArrayList<>();
		raw.add(event("snapshot_created", Map.of("snapshot_id", snapshotId(s.ticker()), "ticker", s.ticker(),
				"name", s.name(), "as_of", AS_OF.toString(), "close", s.close(), "warnings", List.of())));

		turn(raw, "bull", "opening", "get_price_metrics",
				"1년간 127% 오른 상승 추세는 살아 있어요. 고점 대비 43% 내려온 지금은 추세 속 조정 구간이에요.",
				evidence("E1", "PX.RET_1Y", 127.22, "1년 전 종가 대비 상승률이에요. 장기 추세를 볼 때 써요."),
				evidence("E2", "PX.FROM_HIGH_52W", -42.72, "최근 1년 최고가에서 얼마나 내려왔는지예요."));
		turn(raw, "bear", "opening", "get_price_metrics",
				"종가가 20·60·120일 이동평균을 모두 밑돌아요. 추세가 꺾였다는 신호예요.",
				evidence("E1", "PX.VS_MA20", -14.60, "최근 20거래일 평균보다 얼마나 낮은지예요."),
				evidence("E2", "PX.VS_MA120", -21.59, "반년 평균보다도 낮으면 하락 추세로 보는 경우가 많아요."));
		turn(raw, "bull", "rebuttal", "get_price_metrics",
				"하락한 날 거래량이 평소의 0.6배예요. 한꺼번에 던지는 투매로 보긴 어려워요.",
				evidence("E1", "PX.VOLUME_RATIO", 0.60, "오늘 거래량이 평소의 몇 배인지예요."));
		raw.add(event("turn_started", Map.of("side", "bear", "round", "rebuttal")));
		raw.add(event("tool_call", Map.of("side", "bear", "tool", "get_price_metrics")));
		raw.add(event("statement_rejected", Map.of("side", "bear", "round", "rebuttal", "attempt", 1,
				"issues", List.of(Map.of("code", "value_mismatch", "message",
						"E1: PX.VOL_20D 값 70.4은 원본 75.96 (%)과 다릅니다")))));
		accepted(raw, "bear", "rebuttal", 2,
				"변동성이 연율 76%예요. 바닥을 확인하기 전까지 손실 폭이 클 수 있어요.",
				evidence("E1", "PX.VOL_20D", 75.96, "하루하루 가격이 얼마나 들쭉날쭉했는지 1년 기준으로 바꾼 값이에요."));
		turn(raw, "bull", "closing", "get_financials",
				"추세 지표가 약한 건 인정해요. 그래도 " + s.name() + "의 실적이 받쳐준다면 지금은 기회예요.",
				evidence("E1", "PX.RET_6M", 1.66, "반년 전과 비교하면 거의 제자리예요."));
		turn(raw, "bear", "closing", "get_news",
				"실적 기대는 이미 1년 상승에 반영됐어요. 추세가 돌아설 때까지 기다리는 게 나아요.",
				evidence("E1", "PX.RET_1Y", 127.22, "1년 동안 이미 크게 올랐어요."));

		raw.add(event("moderator_started", Map.of()));
		raw.add(event("debate_completed", Map.of(
				"debate_id", workerDebateId,
				"verdict", Map.of(
						"decision", "HOLD",
						"confidence", 0.55,
						"reasoning", "이동평균을 모두 밑돈다는 매도 측 근거는 탄탄해요 [E1]. 하지만 하락일 거래량이 평소의 0.6배라 "
								+ "투매로 단정하기 어렵다는 매수 측 반박도 유효했어요 [E2]. 실적 근거가 양쪽 모두 없어 한쪽으로 기울기 어려워요.",
						"decisive_evidence", List.of("PX.VS_MA120", "PX.VOLUME_RATIO"),
						"scores", Map.of(
								"bull", score(4, 3, 4, 3, "거래량 반박이 좋았지만 실적 근거가 없어요."),
								"bear", score(4, 4, 3, 3, "추세 근거는 탄탄하지만 반박이 약했어요."))),
				"stats", Map.of(
						"bull", Map.of("statements", 3, "first_try_pass_rate", 1.0, "rejected_attempts", 0, "evidence_accuracy", 1.0),
						"bear", Map.of("statements", 3, "first_try_pass_rate", 0.67, "rejected_attempts", 1, "evidence_accuracy", 0.83)),
				// 토론자 Haiku + 중재자 Opus로 한 번 돌렸을 때와 비슷한 양 (≈ $0.26)
				"usage", Map.of("calls", List.of(
						Map.of("model", "claude-haiku-5-5", "input_tokens", 98000, "output_tokens", 21000,
								"cache_read_input_tokens", 61000, "cache_creation_input_tokens", 9000),
						Map.of("model", "claude-opus-5-5", "input_tokens", 20000, "output_tokens", 8000,
								"cache_read_input_tokens", 0, "cache_creation_input_tokens", 0))))));

		List<WorkerEvent> out = new ArrayList<>();
		for (int i = 0; i < raw.size(); i++) {
			Map<String, Object> e = raw.get(i);
			out.add(new WorkerEvent(i + 1, (String) e.get("type"), json.writeValueAsString(e.get("data"))));
		}
		return out;
	}

	/** 단일 모드: 토론 없이 바로 판정. 토론 판정(항상 보류)과 비교가 되도록 종목마다 다른 판정을 낸다 */
	private List<WorkerEvent> single(WorkerStock s) {
		String decision = List.of("BUY", "HOLD", "SELL").get(Math.floorMod(s.ticker().hashCode(), 3));
		List<Map<String, Object>> raw = List.of(
				event("moderator_started", Map.of()),
				event("debate_completed", Map.of(
						"verdict", Map.of("decision", decision, "confidence", 0.6,
								"reasoning", "120일 이동평균 대비 위치를 가장 크게 봤어요 [E1].",
								"decisive_evidence", List.of("PX.VS_MA120")),
						"usage", Map.of("calls", List.of(Map.of("model", "claude-sonnet-5-5", "input_tokens", 9000,
								"output_tokens", 900, "cache_read_input_tokens", 0, "cache_creation_input_tokens", 0))))));
		List<WorkerEvent> out = new ArrayList<>();
		for (int i = 0; i < raw.size(); i++) {
			out.add(new WorkerEvent(i + 1, (String) raw.get(i).get("type"), json.writeValueAsString(raw.get(i).get("data"))));
		}
		return out;
	}

	private static Map<String, Object> event(String type, Map<String, Object> data) {
		return Map.of("type", type, "data", data);
	}

	private static Map<String, Object> evidence(String ref, String sourceId, double value, String interpretation) {
		return Map.of("ref", ref, "source_id", sourceId, "value", value, "interpretation", interpretation);
	}

	private static Map<String, Object> score(int relevance, int materiality, int rebuttal, int risk, String comment) {
		return Map.of("relevance", relevance, "materiality", materiality, "rebuttal", rebuttal,
				"risk_awareness", risk, "comment", comment);
	}

	@SafeVarargs
	private static void turn(List<Map<String, Object>> raw, String side, String round, String tool, String claim,
			Map<String, Object>... evidence) {
		raw.add(event("turn_started", Map.of("side", side, "round", round)));
		raw.add(event("tool_call", Map.of("side", side, "tool", tool)));
		accepted(raw, side, round, 1, claim, evidence);
	}

	@SafeVarargs
	private static void accepted(List<Map<String, Object>> raw, String side, String round, int attempts, String claim,
			Map<String, Object>... evidence) {
		// 실제 워커처럼 주장 뒤에 근거별 설명을 붙인다
		StringBuilder argument = new StringBuilder(claim);
		for (Map<String, Object> e : evidence) {
			argument.append("\n").append(e.get("interpretation")).append(" [").append(e.get("ref")).append("]");
		}
		raw.add(event("statement_accepted", Map.of(
				"side", side, "round", round, "attempts", attempts, "verified", true,
				"statement", Map.of("claim", claim, "argument", argument.toString(), "evidence", List.of(evidence)),
				"warnings", List.of())));
	}
}
