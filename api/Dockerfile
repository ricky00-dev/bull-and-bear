# 빌드: Gradle로 실행 가능한 jar를 만든다. 의존성 층을 먼저 받아 두어 코드만 바뀌면 빠르게 다시 빌드된다.
FROM eclipse-temurin:17-jdk AS build
WORKDIR /src
COPY gradlew settings.gradle* build.gradle* ./
COPY gradle gradle
RUN ./gradlew --no-daemon -q dependencies > /dev/null
COPY src src
RUN ./gradlew --no-daemon -q bootJar -x test && cp build/libs/*-SNAPSHOT.jar /app.jar

# 실행: JRE만. 컨테이너 메모리 한도에 맞춰 힙을 잡는다 (작은 EC2에서 Postgres·워커와 같이 돈다)
FROM eclipse-temurin:17-jre
RUN useradd --system --uid 1001 app
USER app
COPY --from=build /app.jar /app/app.jar
ENV JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=70 -XX:+ExitOnOutOfMemoryError"
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
