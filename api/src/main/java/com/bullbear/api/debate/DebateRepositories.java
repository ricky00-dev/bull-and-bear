package com.bullbear.api.debate;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

interface DebateRepository extends JpaRepository<Debate, UUID> {

	Optional<Debate> findFirstByTickerAndDataDateAndStatusInOrderByCreatedAtDesc(
			String ticker, LocalDate dataDate, Collection<Debate.Status> statuses);

	long countByOriginAndStatus(Debate.Origin origin, Debate.Status status);

	/** 그날 이 사용자가 새로 시작한 토론 수. 워커 요청 전에 실패한 건 세지 않는다. */
	@Query("select count(d) from Debate d where d.requestedBy = :userId and d.debateDay = :day"
			+ " and d.origin = com.bullbear.api.debate.Debate.Origin.USER and d.workerDebateId is not null")
	long countStartedBy(@Param("userId") UUID userId, @Param("day") LocalDate day);

	/** 그날 쓴 LLM 비용. 사용량을 모르는 토론(진행 중·실패)은 estimate로 센다. */
	@Query("select coalesce(sum(coalesce(d.costUsd, :estimate)), 0) from Debate d"
			+ " where d.debateDay = :day and d.origin = :origin and d.workerDebateId is not null")
	BigDecimal costOn(@Param("day") LocalDate day, @Param("origin") Debate.Origin origin,
			@Param("estimate") BigDecimal estimate);

	List<Debate> findByStatus(Debate.Status status);
}

interface DebateEventRepository extends JpaRepository<DebateEvent, Long> {

	List<DebateEvent> findByDebateIdAndSeqGreaterThanOrderBySeq(UUID debateId, long seq);

	boolean existsByDebateIdAndSeq(UUID debateId, long seq);
}
