package com.bullbear.api.rag;

import java.util.UUID;
import org.springframework.web.bind.annotation.*;
import com.bullbear.api.common.ApiException;
import com.bullbear.api.common.ErrorCode;
import com.bullbear.api.debate.Debate;
import com.bullbear.api.debate.DebateService;
import jakarta.validation.Valid;

@RestController
@RequestMapping("/api/debates/{id}/rag")
public class RagController {
    private final DebateService debates;
    private final RagWorkerClient worker;
    public RagController(DebateService debates, RagWorkerClient worker) {
        this.debates = debates;
        this.worker = worker;
    }
    @PostMapping("/search")
    public RagModels.Documents search(@PathVariable UUID id, @Valid @RequestBody RagModels.SearchRequest request) {
        var debate = saved(id);
        return worker.search(new RagModels.WorkerSearch(debate.getSnapshotId(), debate.getTicker(), request.question()));
    }
    @PostMapping("/facts")
    public RagModels.Facts facts(@PathVariable UUID id, @Valid @RequestBody RagModels.FactsRequest request) {
        var debate = saved(id);
        return worker.facts(new RagModels.WorkerFacts(debate.getSnapshotId(), debate.getTicker(),
            request.metric(), request.asOf(), request.unit()));
    }
    private Debate saved(UUID id) {
        var debate = debates.get(id);
        if (debate.getSnapshotId() == null || debate.getSnapshotId().isBlank())
            throw new ApiException(ErrorCode.SNAPSHOT_NOT_READY, "조회할 자료가 아직 준비되지 않았습니다");
        return debate;
    }
}
