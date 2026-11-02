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

## 실제 워커 붙이기

1. FastAPI/HTTP 워커는 구현되어 있다. 실제 모델 완주, 비개발용 토큰, 영속 데이터/비용 장부를
   [워커 운영 안내](WORKER-OPERATIONS.md)에 따라 검증한다. Docker가 없는 PC의 로컬 통합 검증과 실제 서버 배포는 구분한다.
2. 워커는 요청 헤더 `X-Worker-Token`이 환경 변수 `WORKER_TOKEN`과 같은지 확인한다 (Spring이 보냄)
3. `deploy/.env`: `WORKER_MODE=http`, API 키들 입력
4. `docker compose -f deploy/compose.yml --env-file deploy/.env --profile worker up -d --build`
5. 동일 스냅샷 토론/단일 완주·반복 품질/비용·봉인·복구를 확인한 후 전향 운용 활성화를 결정한다.

## 업데이트

```bash
cd ~/bull-and-bear && git pull
docker compose -f deploy/compose.yml --env-file deploy/.env --profile worker up -d --build
```

DB 마이그레이션은 Spring이 켜질 때 Flyway가 자동으로 한다. Spring은 저장된 워커 ID로 상태/이벤트를 다시 조회한다.
워커 프로세스가 중단된 토론은 실패로 복구하며 모델 생성을 자동 재개하지 않는다. 미확정 비용은 유지한다.
배포 중 1분 정도 API가 내려간다 (전시 당일에는 배포하지 않는다).

## 운영 명령

`deploy/backup.sh`는 PostgreSQL만 백업한다. 워커 스냅샷·감사·HTTP 결과·비용 장부는
`worker_data`에 별도로 있으므로 [워커 백업/복구 절차](WORKER-OPERATIONS.md#중단과-복구)도 필요하다.

```bash
docker compose -f deploy/compose.yml --env-file deploy/.env ps        # 상태
docker compose -f deploy/compose.yml --env-file deploy/.env logs -f api   # 로그
docker compose -f deploy/compose.yml --env-file deploy/.env exec postgres psql -U bullbear   # DB
# 오늘 LLM 비용
docker compose -f deploy/compose.yml --env-file deploy/.env exec postgres psql -U bullbear -c \
  "select origin, count(*), sum(cost_usd) from debates where debate_day = current_date group by origin"
```

## 로컬에서 운영 구성 확인

```bash
printf 'POSTGRES_PASSWORD=local\nWORKER_TOKEN=local\n' > deploy/.env
docker compose -f deploy/compose.yml --env-file deploy/.env up -d --build   # http://localhost
docker compose -f deploy/compose.yml --env-file deploy/.env down -v         # 정리 (데이터 삭제)
```
