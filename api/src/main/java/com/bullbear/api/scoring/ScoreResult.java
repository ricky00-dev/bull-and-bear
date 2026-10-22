package com.bullbear.api.scoring;

import java.math.BigDecimal;
import java.time.LocalDate;

record ScoreResult(LocalDate tradeDate, BigDecimal stockClose, BigDecimal indexClose, BigDecimal baseIndex,
		BigDecimal stockReturn, BigDecimal indexReturn, BigDecimal excessReturn, boolean userHit,
		boolean moderatorHit) {
}
