package com.bullbear.api.debate;

import java.time.Instant;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;

interface DebateRepository extends JpaRepository<Debate, UUID> {

	Optional<Debate> findFirstByTickerAndStatusInAndCreatedAtAfterOrderByCreatedAtDesc(
			String ticker, Collection<Debate.Status> statuses, Instant after);

	List<Debate> findByStatus(Debate.Status status);
}

interface DebateEventRepository extends JpaRepository<DebateEvent, Long> {

	List<DebateEvent> findByDebateIdAndSeqGreaterThanOrderBySeq(UUID debateId, long seq);

	boolean existsByDebateIdAndSeq(UUID debateId, long seq);
}
