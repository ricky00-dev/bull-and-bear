package com.bullbear.api.debate;

import java.math.BigDecimal;
import java.time.Clock;
import java.lang.reflect.Proxy;
import org.springframework.jdbc.core.simple.JdbcClient;
import com.bullbear.api.config.BullbearProperties;

/** Test-only package bridge; repository stub has no JDK agent requirement. */
public final class SingleTestComponents {
    public static class ControlledQuota extends DebateQuota {
        public boolean blocked;
        ControlledQuota(DebateRepository repository, JdbcClient jdbc, BullbearProperties properties, Clock clock) {
            super(repository, jdbc, properties, clock);
        }
        @Override public boolean scheduledBudgetOpen(BigDecimal limit) {
            return !blocked && super.scheduledBudgetOpen(limit);
        }
    }
    public static ControlledQuota quota(JdbcClient jdbc, BullbearProperties properties, Clock clock) {
        DebateRepository repository = (DebateRepository) Proxy.newProxyInstance(DebateRepository.class.getClassLoader(),
            new Class<?>[]{DebateRepository.class}, (proxy, method, args) -> {
                if (method.getName().equals("costOn")) return BigDecimal.ZERO;
                throw new UnsupportedOperationException(method.getName());
            });
        return new ControlledQuota(repository, jdbc, properties, clock);
    }
    public static LlmUsage usage(BullbearProperties properties) { return new LlmUsage(properties); }
}
