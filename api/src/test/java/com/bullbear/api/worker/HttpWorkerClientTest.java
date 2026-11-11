package com.bullbear.api.worker;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.net.URI;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicReference;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.reactive.function.client.ClientRequest;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.WebClient;

import com.bullbear.api.config.BullbearProperties;

import reactor.core.publisher.Mono;

class HttpWorkerClientTest {

    private HttpWorkerClient client(String body, AtomicReference<ClientRequest> captured) {
        var builder = WebClient.builder().exchangeFunction(request -> {
            captured.set(request);
            return Mono.just(ClientResponse.create(HttpStatus.OK)
                    .header("Content-Type", "text/event-stream")
                    .body(body).build());
        });
        var worker = new BullbearProperties.Worker("http", URI.create("http://localhost:8000"), "secret", Duration.ZERO);
        return new HttpWorkerClient(builder, new BullbearProperties(null, worker, null, null, null, null, null));
    }

    @Test
    void cleanEofWithoutTerminalFailsForRelayRetry() {
        var client = client("id: 1\nevent: turn_started\ndata: {}\n\n", new AtomicReference<>());
        assertThatThrownBy(() -> client.events("d", 0).collectList().block(Duration.ofSeconds(2)))
                .isInstanceOf(IllegalStateException.class).hasMessageContaining("종료 이벤트 없이");
    }

    @Test
    void terminalEventCompletesAndResumeHeadersAreForwarded() {
        var captured = new AtomicReference<ClientRequest>();
        var client = client(": heartbeat\n\nid: 4\nevent: debate_completed\ndata: {}\n\n", captured);
        var events = client.events("d", 3).collectList().block(Duration.ofSeconds(2));
        assertThat(events).hasSize(1);
        assertThat(events.get(0).seq()).isEqualTo(4);
        assertThat(captured.get().headers().getFirst("X-Worker-Token")).isEqualTo("secret");
        assertThat(captured.get().headers().getFirst("Last-Event-ID")).isEqualTo("3");
    }
}
