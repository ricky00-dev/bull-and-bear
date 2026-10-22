package com.bullbear.api.worker;

import java.math.BigDecimal;
import java.time.LocalDate;

/** 일별 종가 (종목 또는 지수). */
public record DailyClose(LocalDate date, BigDecimal close) {
}
