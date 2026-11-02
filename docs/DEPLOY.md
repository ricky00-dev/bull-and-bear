# 배포 (AWS EC2 한 대)

전시까지는 서버 한 대에 Docker Compose로 전부 올린다. 관람객 수십 명 규모라 이걸로 충분하고,
LLM 호출이 병목이지 서버가 병목이 아니다 (`docs/ARCHITECTURE.md`).

```
인터넷 ─443─▶ Caddy(web) ─┬─ 정적 파일 (React 빌드)
                          └─ /api/* ─▶ Spring(api) ─▶ Postgres
                                          └─ HTTP+SSE ─▶ Python 워커 ─▶ Anthropic / DART / 네이버
```

- 외부에 열린 건 Caddy(80, 443)뿐. Postgres·워커·Spring은 내부 네트워크에만 있다.
- 웹과 API가 같은 출처라 CORS·쿠키 문제가 없다. Caddy가 HTTPS 인증서를 자동으로 받고 갱신한다.
- SSE(토론 스트림)는 Caddy가 버퍼링 없이 흘려보낸다 (로컬에서 확인함).

## 서버 고르기

| 항목 | 권장 | 이유 |
|---|---|---|
| 인스턴스 | **t3.small** (2 vCPU, 2GB), 서울 리전 | 실측: Spring 370MB + Postgres 40MB + Caddy 20MB, 워커(pandas) 추가 시 약 1GB. t3.micro(1GB)는 빠듯함 |
| 디스크 | gp3 20GB | 이미지 빌드 공간 |
| 비용 | 약 월 $20 (AWS 신규 크레딧으로) | 전시 끝나면 중지 |
| 고정 IP | 탄력적 IP 1개 | 재시작해도 주소 유지 (인스턴스에 붙어 있으면 무료) |
| 보안 그룹 | 22(내 IP만), 80, 443 | |

**도메인**: 사지 않아도 된다. `sslip.io`를 쓰면 IP로 된 도메인에 HTTPS 인증서가 붙는다.
예: 탄력적 IP가 `3.35.10.20`이면 `SITE_ADDRESS=3-35-10-20.sslip.io`.
**PWA 설치(홈 화면에 추가)와 서비스 워커는 HTTPS에서만 동작**하므로 전시 전에 꼭 HTTPS로 연다.

## 처음 한 번

```bash
# 1. EC2(Ubuntu 24.04)에 접속해 Docker 설치
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu && exit   # 다시 접속

# 2. 빌드할 때 메모리가 모자라지 않게 스왑 2GB
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 3. 코드 받기 (private 레포: GitHub 배포 키 또는 개인 토큰)
git clone https://github.com/ricky00-dev/bull-and-bear.git && cd bull-and-bear && git checkout develop

# 4. 설정 (비밀값은 openssl rand -hex 24 로 생성)
cp deploy/.env.example deploy/.env && nano deploy/.env

# 5. 실행 (워커 없이 가짜 워커로 시연 경로부터 확인)
docker compose -f deploy/compose.yml --env-file deploy/.env up -d --build

# 6. 백업 cron
(crontab -l 2>/dev/null; echo "0 4 * * * $HOME/bull-and-bear/deploy/backup.sh >> $HOME/backup.log 2>&1") | crontab -
```

## 실제 워커 붙이기 (M2, 워커 FastAPI 완성 후)

1. 워커 의존성에 `fastapi`, `uvicorn` 추가, `bullbear.server:app` 구현 (jangwonii, `docs/worker-api.md`)
2. 워커는 요청 헤더 `X-Worker-Token`이 환경 변수 `WORKER_TOKEN`과 같은지 확인한다 (Spring이 보냄)
3. `deploy/.env`: `WORKER_MODE=http`, API 키들 입력
4. `docker compose -f deploy/compose.yml --env-file deploy/.env --profile worker up -d --build`
5. 토론 한 번 돌려 보고 이상 없으면 `FORWARD_RUN_ENABLED=true` → `up -d`

## 업데이트

```bash
cd ~/bull-and-bear && git pull
docker compose -f deploy/compose.yml --env-file deploy/.env --profile worker up -d --build
docker image prune -f   # 옛 이미지 정리 (디스크 20GB가 빌드마다 줄어든다)
```

DB 마이그레이션은 Spring이 켜질 때 Flyway가 자동으로 한다. 진행 중이던 토론은 재시작 후 이어 받는다.
배포 중 1분 정도 API가 내려간다 (전시 당일에는 배포하지 않는다).

## 운영 명령

```bash
docker compose -f deploy/compose.yml --env-file deploy/.env ps        # 상태
docker compose -f deploy/compose.yml --env-file deploy/.env logs -f api   # 로그
docker compose -f deploy/compose.yml --env-file deploy/.env exec postgres psql -U bullbear   # DB
# 오늘 LLM 비용
docker compose -f deploy/compose.yml --env-file deploy/.env exec postgres psql -U bullbear -c \
  "select origin, count(*), sum(cost_usd) from debates where debate_day = current_date group by origin"
```

한눈에 보기: `deploy/status.sh` (컨테이너, 상태 확인, 디스크·메모리, 오늘 토론·비용·판정·퀴즈, 마지막 백업)

## 감시와 알림

`https://<주소>/healthz`가 상태를 돌려준다. 문제가 있으면 503이다.
- `db`: DB 연결
- `worker`: 실제 워커일 때 워커 `/health` 응답
- `forwardRun`: 전향 운용이 켜져 있으면, 평일 19:30 이후 고정 종목이 오늘 모두 토론됐는지. 실험 데이터가 조용히 빠지는 걸 막는 용도라 가장 중요하다. 휴장일에는 알림이 잘못 갈 수 있다 (11월에는 휴장일 없음).

알림은 **UptimeRobot 무료**로 받는다 (5분 간격, 메일·앱 알림).
1. uptimerobot.com 가입 → Add New Monitor → HTTP(s)
2. URL: `https://<주소>/healthz`, 간격 5분
3. 알림 받을 메일 추가 (팀원 여러 명 가능)

서버 안 감시: 컨테이너는 `restart: unless-stopped`로 죽으면 다시 뜬다. 워커는 30초마다 헬스체크 (`docker compose ps`에 unhealthy로 보인다).

## 백업과 복구

- 백업: 매일 04:00 cron (`deploy/backup.sh`), 서버의 `~/backups`에 14일치.
- 복구: `deploy/restore.sh ~/backups/bullbear-YYYYMMDD-HHMM.sql.gz`. 확인을 묻고, API를 멈춘 뒤 덮어쓰고 다시 켠다.
  로컬 운영 구성에서 백업 → 데이터 변경 → 복구 → API 재기동까지 확인함 (2026-11-02).
- 한계: 백업이 같은 서버에 있어서 서버(디스크)를 잃으면 같이 잃는다. 정식 운용(11/11) 전에 S3로 복사를 붙인다
  (S3 몇 MB는 월 몇 원 수준). 그 전에는 큰 변경 전에 `scp`로 내려받아 둔다.

## 로컬에서 운영 구성 확인

```bash
printf 'POSTGRES_PASSWORD=local\nWORKER_TOKEN=local\n' > deploy/.env
docker compose -f deploy/compose.yml --env-file deploy/.env up -d --build   # http://localhost
docker compose -f deploy/compose.yml --env-file deploy/.env down -v         # 정리 (데이터 삭제)
```
