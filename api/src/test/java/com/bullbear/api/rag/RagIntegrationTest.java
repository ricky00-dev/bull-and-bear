package com.bullbear.api.rag;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.*;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.reactive.function.client.WebClient;
import com.bullbear.api.auth.*;
import com.bullbear.api.common.*;
import com.bullbear.api.config.BullbearProperties;
import com.bullbear.api.debate.*;
import com.bullbear.api.user.*;
import tools.jackson.databind.json.JsonMapper;

/** Real HTTP codec + controller + auth, with only a local worker stub (no models or DB). */
class RagIntegrationTest {
    // These collaborators are not final; avoid JVM agent attachment for this local HTTP test.
    private static <T> T mock(Class<T> type) {
        return org.mockito.Mockito.mock(type, withSettings().mockMaker(org.mockito.MockMakers.SUBCLASS));
    }
    private HttpServer server;
    private MockMvc mvc;
    private DebateService debates;
    private Debate debate;
    private final UUID id = UUID.randomUUID();
    private final AtomicInteger calls = new AtomicInteger();
    private String path, token, body;
    private int status = 200;
    private String response;
    private static final String DOCS = """
        {"snapshot_id":"saved","context_id":"ctx","ticker":"005930","snapshot_as_of":"2026-10-30",
        "mode":"documents","answerability":"documents_found","reasons":[],
        "answer_scope":"retrieved_documents_not_verified_numeric_answer",
        "documents":[{"chunk_id":"per","text":"PER 설명","horizons":["common"],"applicability":"개념","limitations":["예측 아님"]}],
        "moderator_verdict":{"decision":"BUY"},"facts":[{"value":999}]}""";
    private static final String FACTS = """
        {"snapshot_id":"saved","context_id":"ctx","ticker":"005930","snapshot_as_of":"2026-10-30",
        "mode":"facts","answerability":"supported_fact","reasons":[],
        "facts":[{"fact_id":"VAL.PER_TTM","ticker":"005930","value":12.3,"unit":"x","as_of":"2026-10-30",
        "source":"derived","inputs":["PX.CLOSE"],"verified_lineage":["PX.CLOSE","VAL.PER_TTM"]}],
        "moderator_verdict":"SECRET","documents":[{"text":"hidden"}]}""";

    @BeforeEach void setup() throws Exception {
        response = DOCS;
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            calls.incrementAndGet();
            path = exchange.getRequestURI().getPath();
            token = exchange.getRequestHeaders().getFirst("X-Worker-Token");
            body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            byte[] bytes = response.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(status, bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.close();
        });
        server.start();
        debates = mock(DebateService.class);
        debate = mock(Debate.class);
        when(debate.getSnapshotId()).thenReturn("saved");
        when(debate.getTicker()).thenReturn("005930");
        when(debates.get(id)).thenReturn(debate);
        mvc = mvc("http");
    }
    private MockMvc mvc(String mode) {
        var properties = new BullbearProperties(null, new BullbearProperties.Worker(mode,
            URI.create("http://127.0.0.1:" + server.getAddress().getPort()), "worker-secret", Duration.ZERO), null, null, null, null);
        var users = mock(UserRepository.class);
        var tokens = new TokenService();
        when(users.findByTokenHash(tokens.hash("guest"))).thenReturn(Optional.of(mock(User.class)));
        return MockMvcBuilders.standaloneSetup(new RagController(debates, new RagWorkerClient(WebClient.builder(), properties)))
            .setControllerAdvice(new GlobalExceptionHandler())
            .addInterceptors(new AuthInterceptor(users, tokens)).build();
    }
    @AfterEach void close() { server.stop(0); }
    private org.springframework.test.web.servlet.ResultActions send(String suffix, String content) throws Exception {
        return mvc.perform(post("/api/debates/" + id + "/rag/" + suffix).header("Authorization", "Bearer guest")
            .contentType("application/json").content(content));
    }
    @Test void documentsUseSavedIdentityAndNeverExposeVerdictOrFacts() throws Exception {
        send("search", "{\"question\":\"PER 뜻과 현재 값\"}").andExpect(status().isOk())
            .andExpect(jsonPath("$.documents[0].text").value("PER 설명"))
            .andExpect(jsonPath("$.facts").doesNotExist()).andExpect(jsonPath("$.moderator_verdict").doesNotExist());
        assertThat(path).isEqualTo("/rag/search");
        assertThat(token).isEqualTo("worker-secret");
        var json = JsonMapper.builder().build().readTree(body);
        assertThat(json.get("snapshot_id").asText()).isEqualTo("saved");
        assertThat(json.get("ticker").asText()).isEqualTo("005930");
        assertThat(json.get("question").asText()).isEqualTo("PER 뜻과 현재 값");
        assertThat(json.has("metric")).isFalse();
        verify(debates).get(id);
        verifyNoMoreInteractions(debates);
    }
    @Test void factsForwardExplicitFieldsAndOnlyReturnFacts() throws Exception {
        response = FACTS;
        send("facts", "{\"metric\":\"per_ttm\",\"asOf\":\"2026-10-30\",\"unit\":\"x\"}")
            .andExpect(status().isOk()).andExpect(jsonPath("$.facts[0].value").value(12.3))
            .andExpect(jsonPath("$.documents").doesNotExist()).andExpect(jsonPath("$.moderator_verdict").doesNotExist());
        assertThat(path).isEqualTo("/rag/facts");
        var json = JsonMapper.builder().build().readTree(body);
        assertThat(json.get("as_of").asText()).isEqualTo("2026-10-30");
        assertThat(json.get("metric").asText()).isEqualTo("per_ttm");
        assertThat(json.get("unit").asText()).isEqualTo("x");
        assertThat(json.has("question")).isFalse();
    }
    @Test void missingEvidenceIsNotATransportFailure() throws Exception {
        response = """
            {"snapshot_id":"saved","context_id":"ctx","ticker":"005930","snapshot_as_of":"2026-10-30",
            "mode":"facts","answerability":"insufficient_evidence","reasons":["fact_date_mismatch"],"facts":[]}""";
        send("facts", "{\"metric\":\"close\"}").andExpect(status().isOk())
            .andExpect(jsonPath("$.reasons[0]").value("fact_date_mismatch"));
    }
    @Test void rejectsMixedUnknownAndInvalidFieldsBeforeCallingWorker() throws Exception {
        for (var content : new String[]{"{}", "{\"question\":\" \"}", "{\"question\":\"PER\",\"metric\":\"pbr\"}",
            "{\"question\":\"PER\",\"ticker\":\"000660\"}"}) send("search", content).andExpect(status().isBadRequest());
        for (var content : new String[]{"{}", "{\"metric\":\"future_price\"}", "{\"metric\":\"close\",\"question\":\"종가\"}",
            "{\"metric\":\"close\",\"asOf\":\"2026-99-99\"}", "{\"metric\":\"close\",\"unit\":\"USD\"}"})
            send("facts", content).andExpect(status().isBadRequest());
        assertThat(calls).hasValue(0);
        verifyNoInteractions(debates);
    }
    @Test void requiresAuthentication() throws Exception {
        mvc.perform(post("/api/debates/" + id + "/rag/search").contentType("application/json").content("{\"question\":\"PER\"}"))
            .andExpect(status().isUnauthorized());
        assertThat(calls).hasValue(0);
    }
    @Test void missingSnapshotNeverStartsAnything() throws Exception {
        when(debate.getSnapshotId()).thenReturn(null);
        send("search", "{\"question\":\"PER\"}").andExpect(status().isConflict())
            .andExpect(jsonPath("$.error.code").value("SNAPSHOT_NOT_READY"));
        assertThat(calls).hasValue(0);
        verify(debates).get(id);
        verifyNoMoreInteractions(debates);
    }
    @Test void transportErrorsAndWrongSnapshotAreNotEmptySuccess() throws Exception {
        status = 503;
        send("search", "{\"question\":\"PER\"}").andExpect(status().isServiceUnavailable());
        status = 404;
        send("search", "{\"question\":\"PER\"}").andExpect(status().isNotFound());
        status = 200;
        response = DOCS.replace("saved", "wrong");
        send("search", "{\"question\":\"PER\"}").andExpect(status().isServiceUnavailable());
    }
    @Test void fakeModeDoesNotInventResultsOrContactWorker() throws Exception {
        mvc = mvc("fake");
        send("search", "{\"question\":\"PER\"}").andExpect(status().isServiceUnavailable());
        assertThat(calls).hasValue(0);
    }
}
