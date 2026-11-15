package com.bullbear.api.debate;

import static org.mockito.Mockito.*;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

class StreamCompletionRaceTest {
    @Test
    void publishDuringRegistrationCannotOvertakeReplay() throws Exception {
        var id = UUID.randomUUID();
        var events = mock(DebateEventRepository.class);
        var debates = mock(DebateRepository.class);
        var debate = mock(Debate.class);
        var hub = new DebateStreamHub(events, debates);
        when(debates.findById(id)).thenReturn(Optional.of(debate));
        when(debate.getStatus()).thenReturn(Debate.Status.RUNNING);
        when(events.findByDebateIdAndSeqGreaterThanOrderBySeq(id, 0L)).thenReturn(List.of(
            new DebateEvent(id, 1L, "statement_accepted", "{}"),
            new DebateEvent(id, 2L, "statement_accepted", "{}")));
        try (var emitters = mockConstruction(SseEmitter.class, (emitter, context) -> {
            // Producer commits seq 2 and publishes before subscribe starts replay.
            doAnswer(call -> {
                hub.publish(id, new ClientEvent(2L, "statement_accepted", "{}"), false);
                return null;
            }).when(emitter).onCompletion(any(Runnable.class));
        })) {
            hub.subscribe(id, 0L);
            var emitter = emitters.constructed().get(0);
            verify(emitter, times(2)).send(any(SseEmitter.SseEventBuilder.class));
            verify(emitter, never()).complete();
        }
    }

    @ParameterizedTest
    @EnumSource(value = Debate.Status.class, names = {"COMPLETED", "FAILED"})
    void completionBetweenReplayQueryAndStatusReadMustNotDropLastStatements(Debate.Status terminal) throws Exception {
        var id = UUID.randomUUID();
        var events = mock(DebateEventRepository.class);
        var debates = mock(DebateRepository.class);
        var debate = mock(Debate.class);
        var finished = new AtomicBoolean(false);
        var early = new DebateEvent(id, 1L, "statement_accepted", "{}");
        var late = new DebateEvent(id, 2L, "statement_accepted", "{}");
        when(events.findByDebateIdAndSeqGreaterThanOrderBySeq(eq(id), anyLong())).thenAnswer(call -> {
            if (!finished.getAndSet(true)) {
                // Query sees its earlier committed snapshot; producer commits the last event now.
                return List.of(early);
            }
            return (long) call.getArgument(1) == 0L ? List.of(early, late) : List.of(late);
        });
        when(debates.findById(id)).thenReturn(Optional.of(debate));
        when(debate.getStatus()).thenAnswer(call -> finished.get() ? terminal : Debate.Status.RUNNING);
        try (var emitters = mockConstruction(SseEmitter.class)) {
            new DebateStreamHub(events, debates).subscribe(id, 0);
            var emitter = emitters.constructed().get(0);
            verify(emitter, times(2)).send(any(SseEmitter.SseEventBuilder.class));
            verify(emitter).complete();
        }
    }

    @Test
    void replayAndWaitingPublishSendEachEventOnceAndSealTheVerdict() throws Exception {
        var id = UUID.randomUUID();
        var events = mock(DebateEventRepository.class);
        var debates = mock(DebateRepository.class);
        var debate = mock(Debate.class);
        var hub = new DebateStreamHub(events, debates);
        when(debates.findById(id)).thenReturn(Optional.of(debate));
        when(debate.getStatus()).thenReturn(Debate.Status.COMPLETED);
        when(events.findByDebateIdAndSeqGreaterThanOrderBySeq(id, 4L)).thenReturn(List.of(
            new DebateEvent(id, 5L, "statement_accepted", "{}"),
            new DebateEvent(id, 6L, "debate_completed", "{\"verdict\":\"PRIVATE\"}")));
        when(events.findByDebateIdAndSeqGreaterThanOrderBySeq(id, 6L)).thenReturn(List.of());
        try (var emitters = mockConstruction(SseEmitter.class)) {
            hub.subscribe(id, 4L);
            hub.publish(id, ClientEvent.from(6L, "debate_completed", "PRIVATE"), true);
            var emitter = emitters.constructed().get(0);
            var sent = org.mockito.ArgumentCaptor.forClass(SseEmitter.SseEventBuilder.class);
            verify(emitter, times(2)).send(sent.capture());
            String wire = sent.getAllValues().stream().flatMap(b -> b.build().stream())
                .map(d -> String.valueOf(d.getData())).collect(java.util.stream.Collectors.joining());
            org.junit.jupiter.api.Assertions.assertTrue(wire.contains("debate_sealed"));
            org.junit.jupiter.api.Assertions.assertFalse(wire.contains("PRIVATE"));
            verify(emitter).complete();
        }
    }
}
