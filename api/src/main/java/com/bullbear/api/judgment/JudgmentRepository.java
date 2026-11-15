package com.bullbear.api.judgment;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

public interface JudgmentRepository extends JpaRepository<Judgment, UUID> {

	interface DecisionCount {
		Decision getDecision();

		long getCount();
	}

	List<Judgment> findByUserIdOrderByCreatedAtDesc(UUID userId);

	Optional<Judgment> findByUserIdAndDebateId(UUID userId, UUID debateId);

	@Query("select j.decision as decision, count(j) as count from Judgment j where j.debateId = :debateId group by j.decision")
	List<DecisionCount> countByDecision(UUID debateId);
}
