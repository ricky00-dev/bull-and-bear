package com.bullbear.api;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;

import com.bullbear.api.worker.HttpWorkerClient;
import com.bullbear.api.worker.WorkerClient;

/**
 * 실제 워커 모드(http)로 앱이 뜨는지. 다른 테스트는 모두 가짜 워커라 이 설정은 따로 확인해야 한다
 * (Spring Boot 4는 WebClient.Builder가 spring-boot-starter-webclient에 있어서 빠뜨리면 http 모드만 못 뜬다).
 */
@Import(TestcontainersConfiguration.class)
@SpringBootTest(properties = "bullbear.worker.mode=http")
class HttpWorkerModeTest {

	@Autowired
	WorkerClient worker;

	@Test
	void http_모드에서는_실제_워커_클라이언트를_쓴다() {
		assertThat(worker).isInstanceOf(HttpWorkerClient.class);
	}
}
