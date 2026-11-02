package com.bullbear.api.rag;

import java.time.Duration;
import java.util.Objects;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import com.bullbear.api.common.ApiException;
import com.bullbear.api.common.ErrorCode;
import com.bullbear.api.config.BullbearProperties;

/** Read-only saved-snapshot queries. No debate start, market collection or model fallback. */
@Component
public class RagWorkerClient {
    private final WebClient http;
    private final boolean enabled;
    public RagWorkerClient(WebClient.Builder builder, BullbearProperties properties) {
        enabled = "http".equals(properties.worker().mode());
        http = builder.baseUrl(properties.worker().baseUrl().toString())
            .defaultHeader("X-Worker-Token", properties.worker().token()).build();
    }
    public RagModels.Documents search(RagModels.WorkerSearch request) {
        var result = post("/rag/search", request, RagModels.Documents.class);
        if (!Objects.equals(result.snapshotId(), request.snapshotId()) || !Objects.equals(result.ticker(), request.ticker())
            || !"documents".equals(result.mode()) || result.documents() == null
            || !"retrieved_documents_not_verified_numeric_answer".equals(result.answerScope())) throw unavailable();
        return result;
    }
    public RagModels.Facts facts(RagModels.WorkerFacts request) {
        var result = post("/rag/facts", request, RagModels.Facts.class);
        if (!Objects.equals(result.snapshotId(), request.snapshotId()) || !Objects.equals(result.ticker(), request.ticker())
            || !"facts".equals(result.mode()) || result.facts() == null) throw unavailable();
        return result;
    }
    private <T> T post(String path, Object body, Class<T> type) {
        if (!enabled) throw new ApiException(ErrorCode.WORKER_UNAVAILABLE, "자료 조회는 실제 워커 연결이 필요합니다");
        try {
            var result = http.post().uri(path).bodyValue(body).retrieve().bodyToMono(type).block(Duration.ofSeconds(15));
            if (result == null) throw unavailable();
            return result;
        } catch (WebClientResponseException e) {
            if (e.getStatusCode().value() == 404) throw new ApiException(ErrorCode.NOT_FOUND, "저장된 자료를 찾을 수 없습니다");
            if (e.getStatusCode().value() == 400) throw new ApiException(ErrorCode.INVALID_REQUEST, "조회 조건을 확인해 주세요");
            throw unavailable();
        } catch (ApiException e) {
            throw e;
        } catch (RuntimeException e) {
            throw unavailable();
        }
    }
    private ApiException unavailable() {
        return new ApiException(ErrorCode.WORKER_UNAVAILABLE, "자료 조회를 완료하지 못했습니다. 잠시 후 다시 시도해 주세요");
    }
}
