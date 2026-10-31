package com.bullbear.api.experiment;

import static org.assertj.core.api.Assertions.assertThat;

import java.math.BigDecimal;
import java.time.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicReference;

import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import com.bullbear.api.config.BullbearProperties;
import com.bullbear.api.debate.*;
import com.bullbear.api.worker.*;

import reactor.core.publisher.Flux;
import tools.jackson.databind.json.JsonMapper;

/** Real PostgreSQL/Flyway with a scripted worker; no Docker or model calls. */
@EnabledIfEnvironmentVariable(named = "BULLBEAR_TEST_JDBC_URL", matches = ".+")
class SingleVerdictRecoveryTest {
    DriverManagerDataSource ds;
    JdbcClient jdbc;
    String schema;
    Flyway flyway;
    UUID debate;
    ScriptedWorker worker;
    SingleTestComponents.ControlledQuota quota;
    LlmUsage usage;
    BullbearProperties properties;
    Clock clock;
    AtomicReference<Instant> now;
    List<SingleVerdictRunner> runners = new ArrayList<>();


    static class ScriptedWorker implements WorkerClient {
        boolean loseFirstAck;
        List<String> keys = new ArrayList<>(), ids = new ArrayList<>();
        Queue<Flux<WorkerEvent>> streams = new ArrayDeque<>();
        public WorkerDebateStarted startSingle(String ticker, String snapshot, String key) {
            assertThat(ticker).isEqualTo("005930");
            assertThat(snapshot).isEqualTo("snap-frozen");
            keys.add(key);
            if (loseFirstAck && keys.size() == 1) throw new IllegalStateException("lost ack");
            return new WorkerDebateStarted("worker-1", snapshot, "running", keys.size() > 1);
        }
        public Flux<WorkerEvent> events(String id, long seq) {
            assertThat(seq).isZero();
            ids.add(id);
            return streams.remove();
        }
        public List<WorkerStock> search(String q, int limit) { throw new UnsupportedOperationException(); }
        public WorkerStockDetail stock(String ticker) { throw new UnsupportedOperationException(); }
        public WorkerDebateStarted startDebate(String t, String r) { throw new UnsupportedOperationException(); }
        public List<DailyClose> dailyCloses(String t, LocalDate a, LocalDate b) { throw new UnsupportedOperationException(); }
        public List<DailyClose> indexCloses(String t, LocalDate a, LocalDate b) { throw new UnsupportedOperationException(); }
    }

    @BeforeEach
    void setup() throws Exception {
        schema = "single_review_" + UUID.randomUUID().toString().replace("-", "");
        String url = System.getenv("BULLBEAR_TEST_JDBC_URL");
        ds = new DriverManagerDataSource(url + (url.contains("?") ? "&" : "?") + "currentSchema=" + schema,
                System.getenv().getOrDefault("BULLBEAR_TEST_DB_USER", "postgres"), "");
        flyway = Flyway.configure().dataSource(ds).schemas(schema).defaultSchema(schema)
                .locations("classpath:db/migration").target("6").load();
        flyway.migrate();
        jdbc = JdbcClient.create(ds);
        debate = UUID.randomUUID();
        jdbc.sql("""
            insert into debates (id,ticker,stock_name,status,snapshot_id,trade_date,created_at,origin,debate_day,data_date)
            values (:id,'005930','fixture','COMPLETED','snap-frozen','2026-11-11',now(),'SCHEDULED','2026-11-11','2026-11-11')
            """).param("id", debate).update();
        now = new AtomicReference<>(Instant.parse("2026-11-11T08:00:00Z"));
        clock = new Clock() {
            public ZoneId getZone() { return ZoneId.of("Asia/Seoul"); }
            public Clock withZone(ZoneId zone) { return Clock.fixed(instant(), zone); }
            public Instant instant() { return now.get(); }
        };
        properties = new BullbearProperties(null, null, null,
            new BullbearProperties.Budget(BigDecimal.TEN, 5, new BigDecimal("0.15"), Map.of()),
            new BullbearProperties.ForwardRun(false, List.of(), "", 1, BigDecimal.TEN, Duration.ofMinutes(5)),
            new BullbearProperties.Experiment(LocalDate.of(2026,11,11), false, 3));
        quota = SingleTestComponents.quota(jdbc, properties, clock);
        usage = SingleTestComponents.usage(properties);
        worker = new ScriptedWorker();
    }

    void migrate() {
        Flyway.configure().dataSource(ds).schemas(schema).defaultSchema(schema).locations("classpath:db/migration").load().migrate();
    }

    SingleVerdictRunner runner() {
        var r = new SingleVerdictRunner(jdbc, worker, quota, usage, JsonMapper.builder().build(), properties,
                clock, new DataSourceTransactionManager(ds));
        runners.add(r);
        return r;
    }

    WorkerEvent end(boolean success, String cost) {
        String v = success ? "\"verdict\":{\"decision\":\"HOLD\",\"confidence\":0.5,\"reasoning\":\"fixture\"}"
            : "\"error\":{\"message\":\"fixture failure\"}";
        return new WorkerEvent(2, success ? "debate_completed" : "debate_failed",
            "{" + v + (cost == null ? "" : ",\"usage\":{\"cost_usd\":" + cost + "}") + "}");
    }

    String status() { return jdbc.sql("select status from single_verdicts").query(String.class).single(); }
    int attempts() { return jdbc.sql("select count(*) from single_verdict_attempts").query(Integer.class).single(); }

    @AfterEach
    void close() {
        runners.forEach(SingleVerdictRunner::destroy);
        if (jdbc != null && schema.startsWith("single_review_")) jdbc.sql("drop schema " + schema + " cascade").update();
    }

    @Test
    void retriesPreserveCostsAndDatesAndUnknownEstimates() {
        migrate();
        worker.streams.addAll(List.of(Flux.just(end(false,"0.10")), Flux.just(end(false,null)), Flux.just(end(true,"0.20"))));
        var r = runner();
        assertThat(r.runDue()).isZero();
        assertThat(quota.scheduledBudgetOpen(new BigDecimal("0.24"))).isFalse();
        now.set(Instant.parse("2026-11-12T08:00:00Z"));
        assertThat(r.runDue()).isZero();
        assertThat(quota.scheduledBudgetOpen(new BigDecimal("0.29"))).isFalse();
        assertThat(r.runDue()).isEqualTo(1);
        assertThat(r.runDue()).isZero();
        assertThat(attempts()).isEqualTo(3);
        assertThat(jdbc.sql("select cost_usd from single_verdict_attempts order by attempt").query(BigDecimal.class).list())
            .containsExactly(new BigDecimal("0.1000"), null, new BigDecimal("0.2000"));
        assertThat(jdbc.sql("select run_day from single_verdict_attempts order by attempt").query(LocalDate.class).list())
            .containsExactly(LocalDate.of(2026,11,11),LocalDate.of(2026,11,12),LocalDate.of(2026,11,12));
        assertThat(quota.scheduledBudgetOpen(new BigDecimal("0.49"))).isFalse();
    }

    @Test
    void lostPostAcknowledgementReplaysSameKeyEvenAfterRestart() {
        migrate();
        worker.loseFirstAck = true;
        assertThat(runner().runDue()).isZero();
        assertThat(status()).isEqualTo("RUNNING");
        quota.blocked = true;
        worker.streams.add(Flux.just(end(true,null)));
        assertThat(runner().runDue()).isEqualTo(1);
        assertThat(worker.keys).containsExactly("single-"+debate+"-1", "single-"+debate+"-1");
        assertThat(attempts()).isEqualTo(1);
    }

    @Test
    void streamErrorsAndEmptyEofResumeSameWorkerWithoutConsumingAttempts() {
        migrate();
        worker.streams.addAll(List.of(Flux.error(new IllegalStateException("disconnected")),
            Flux.empty(), Flux.just(end(true,"0.20"))));
        assertThat(runner().runDue()).isZero();
        assertThat(runner().runDue()).isZero();
        quota.blocked = true;
        assertThat(runner().runDue()).isEqualTo(1);
        assertThat(worker.keys).hasSize(1);
        assertThat(worker.ids).containsExactly("worker-1", "worker-1", "worker-1");
        assertThat(attempts()).isEqualTo(1);
    }

    @Test
    void terminalFailuresAloneConsumeMaxAttempts() {
        migrate();
        worker.streams.addAll(List.of(Flux.just(end(false,null)), Flux.just(end(false,null)), Flux.just(end(false,null))));
        var r = runner();
        for (int i=0;i<5;i++) assertThat(r.runDue()).isZero();
        assertThat(attempts()).isEqualTo(3);
        assertThat(worker.keys).containsExactly("single-"+debate+"-1", "single-"+debate+"-2", "single-"+debate+"-3");
    }

    @Test
    void terminalSaveRollsBackLedgerAndProjectionTogetherAndReplaysWithoutNewExecution() {
        migrate();
        worker.streams.add(Flux.defer(() -> {
            jdbc.sql("alter table single_verdicts add constraint review_save_failure check (status <> 'COMPLETED')").update();
            return Flux.just(end(true,"0.20"));
        }));
        assertThat(runner().runDue()).isZero();
        assertThat(status()).isEqualTo("RUNNING");
        assertThat(jdbc.sql("select status from single_verdict_attempts").query(String.class).single()).isEqualTo("RUNNING");
        assertThat(jdbc.sql("select count(*) from single_verdict_attempts where cost_usd is null").query(Integer.class).single()).isEqualTo(1);
        jdbc.sql("alter table single_verdicts drop constraint review_save_failure").update();
        worker.streams.add(Flux.just(end(true,"0.20")));
        assertThat(runner().runDue()).isEqualTo(1);
        assertThat(worker.keys).hasSize(1);
        assertThat(attempts()).isEqualTo(1);
    }

    @Test
    void migrationPreservesV6CostAndRecoversRunningIdentity() {
        jdbc.sql("""
            insert into single_verdicts (debate_id,worker_id,status,attempts,cost_usd,run_day,created_at)
            values (:id,'legacy-worker','RUNNING',2,null,'2026-11-11',now())
            """).param("id",debate).update();
        migrate();
        assertThat(jdbc.sql("select request_id from single_verdict_attempts").query(String.class).single())
            .isEqualTo("single-"+debate+"-2");
        worker.streams.add(Flux.just(end(true,"0.22")));
        assertThat(runner().runDue()).isEqualTo(1);
        assertThat(worker.keys).isEmpty();
        assertThat(worker.ids).containsExactly("legacy-worker");
        assertThat(attempts()).isEqualTo(1);
    }

    @Test
    void migrationPreservesCompletedLegacyChargeWithoutInventingPriorCosts() {
        jdbc.sql("""
            insert into single_verdicts (debate_id,status,attempts,cost_usd,run_day,created_at)
            values (:id,'COMPLETED',3,0.42,'2026-11-11',now())
            """).param("id",debate).update();
        migrate();
        assertThat(attempts()).isEqualTo(1);
        assertThat(jdbc.sql("select cost_usd from single_verdict_attempts").query(BigDecimal.class).single())
            .isEqualByComparingTo("0.42");
        assertThat(runner().runDue()).isZero();
    }
}
