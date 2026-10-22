package com.bullbear.api.debate;

import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;

public interface ModeratorVerdictRepository extends JpaRepository<ModeratorVerdict, UUID> {
}
