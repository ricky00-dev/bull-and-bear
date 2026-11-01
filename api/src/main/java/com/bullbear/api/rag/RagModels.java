package com.bullbear.api.rag;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import com.fasterxml.jackson.annotation.JsonAnySetter;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

/** Separate input/output schemas; never proxy arbitrary worker JSON (sealed verdicts). */
public final class RagModels {
    private RagModels() {}

    public interface StrictRequest {
        @JsonAnySetter
        default void unknown(String key, Object value) {
            throw new IllegalArgumentException("지원하지 않는 필드: " + key);
        }
    }
    public record SearchRequest(@NotBlank @Size(max=1000) String question) implements StrictRequest {}
    public record FactsRequest(
        @NotBlank @Pattern(regexp="close|per_ttm|pbr|roe_ttm|operating_margin_ttm|market_cap") String metric,
        LocalDate asOf,
        @Pattern(regexp="KRW|KRW/share|%|x|shares|count") String unit) implements StrictRequest {}

    public record WorkerSearch(@JsonProperty("snapshot_id") String snapshotId, String ticker, String question) {}
    public record WorkerFacts(@JsonProperty("snapshot_id") String snapshotId, String ticker, String metric,
        @JsonProperty("as_of") LocalDate asOf, String unit) {}

    @JsonIgnoreProperties(ignoreUnknown=true)
    public record Document(@JsonProperty("chunk_id") String chunkId, String text, List<String> horizons,
        String applicability, List<String> limitations) {}
    @JsonIgnoreProperties(ignoreUnknown=true)
    public record Fact(@JsonProperty("fact_id") String factId, String ticker, BigDecimal value, String unit,
        @JsonProperty("as_of") LocalDate asOf, String source, List<String> inputs,
        @JsonProperty("verified_lineage") List<String> verifiedLineage) {}
    @JsonIgnoreProperties(ignoreUnknown=true)
    public record Documents(@JsonProperty("snapshot_id") String snapshotId,
        @JsonProperty("context_id") String contextId, String ticker,
        @JsonProperty("snapshot_as_of") LocalDate snapshotAsOf, String mode, String answerability,
        List<String> reasons, @JsonProperty("answer_scope") String answerScope, List<Document> documents) {}
    @JsonIgnoreProperties(ignoreUnknown=true)
    public record Facts(@JsonProperty("snapshot_id") String snapshotId,
        @JsonProperty("context_id") String contextId, String ticker,
        @JsonProperty("snapshot_as_of") LocalDate snapshotAsOf, String mode, String answerability,
        List<String> reasons, List<Fact> facts) {}
}
