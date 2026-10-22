package com.bullbear.api.scoring;

import java.util.Collection;
import java.util.List;
import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;

public interface JudgmentScoreRepository extends JpaRepository<JudgmentScore, Long> {

	List<JudgmentScore> findByStatus(JudgmentScore.Status status);

	List<JudgmentScore> findByJudgmentIdIn(Collection<UUID> judgmentIds);

	boolean existsByJudgmentId(UUID judgmentId);
}
