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

## 지금 운영 중인 서버 (2026-11-10)

| 항목 | 값 |
|---|---|
| 주소 | https://54-253-242-203.sslip.io (전시장 화면 `/exhibit`) |
| 서버 | EC2 t3.small, Ubuntu 26.04, 디스크 20GB, 스왑 2GB, 시간대 KST |
| 리전 | **시드니(ap-southeast-2)**. AWS 무료 플랜은 처음 배정된 리전 하나만 쓸 수 있어 서울을 못 고름. 한국에서 요청당 0.1~0.15초 더 걸리지만 토론(수십 초)에 비하면 작음. KRX·DART·Anthropic 모두 시드니에서 정상 응답 확인 |
| 계정 | 무료 플랜(카드 미등록, 크레딧 안에서만 동작). 서울로 옮기려면 유료 플랜 전환 필요 |
| 접속 | `ssh -i ~/.ssh/bullbear.pem ubuntu@54.253.242.203` (키는 조성빈 맥에만. 보안 그룹 SSH는 등록한 IP만 허용) |
| 워커 | 가짜 워커(`WORKER_MODE=fake`). 실제 워커는 엔진 확정 뒤 |
| 백업 | cron 매일 04:00 `deploy/backup.sh` |

서버에는 GitHub 권한을 주지 않았다. 코드는 맥에서 올린다 (아래 "업데이트").

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
# 맥에서: develop 최신 코드를 서버에 덮어쓴다 (deploy/.env는 git에 없으니 그대로 남는다)
git fetch && git archive origin/develop | ssh -i ~/.ssh/bullbear.pem ubuntu@54.253.242.203 'tar xf - -C ~/bull-and-bear'
# 서버에서
cd ~/bull-and-bear
docker compose -f deploy/compose.yml --env-file deploy/.env --profile worker up -d --build
docker image prune -f   # 옛 이미지 정리 (디스크 20GB가 빌드마다 줄어든다)
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

## 전시장 노트북 화면

노트북 브라우저로 `https://<배포 주소>/exhibit`를 열고 전체 화면(F11, 맥은 ⌃⌘F)으로 둔다.

- 큰 QR(관람객 입장), 오늘 퀴즈 랭킹(15초마다), 오늘의 토론 판정 수(30초마다)가 알아서 갱신된다
- QR에는 지금 연 주소가 들어간다. 노트북에서 로컬로 띄우는 경우에만 `web/.env.local`의 `VITE_PUBLIC_URL`에 배포 주소를 넣는다
- 화면 꺼짐은 브라우저가 지원하면 막는다(Wake Lock). 그래도 노트북 절전·화면보호기는 꺼 둔다
- 노트북도 게스트 하나로 접속하므로 랭킹·판정 수에는 영향이 없다

## 카카오 로그인

키가 없으면 버튼이 "카카오로 시작 (준비 중)"으로 보이고 나머지는 그대로 동작한다.

1. [카카오 developers](https://developers.kakao.com) → 내 애플리케이션 → 애플리케이션 추가 (앱 이름 "불앤베어")
2. 앱 설정 → 플랫폼 → **Web** 사이트 도메인: `https://배포주소`, `http://localhost:5173`
3. 카카오 로그인 → **활성화 ON**, Redirect URI: `https://배포주소/auth/kakao`, `http://localhost:5173/auth/kakao`
4. 동의항목은 **아무것도 켜지 않는다** (회원번호만 쓴다. 이름·이메일을 받으면 개인정보 처리방침을 고쳐야 한다)
5. 앱 키 → **REST API 키**를 `deploy/.env`의 `KAKAO_REST_KEY`에 넣고 `up -d` 다시 실행
   - 보안 → 클라이언트 시크릿을 "사용함"으로 켰다면 그 값도 `KAKAO_CLIENT_SECRET`에
   - 로컬: `api/.env`에 `KAKAO_REST_KEY=...` 한 줄 (커밋 금지, .gitignore에 있음) 후 API 재시작

동작: 게스트로 쌓은 판정·퀴즈 기록은 카카오 계정에 그대로 이어진다. 다른 기기에서 같은 카카오로 들어오면 그 기기의 게스트 기록을 합친다(같은 토론을 양쪽에서 판정했으면 먼저 가입한 쪽 판정을 남긴다).

## 로컬에서 운영 구성 확인

```bash
printf 'POSTGRES_PASSWORD=local\nWORKER_TOKEN=local\n' > deploy/.env
docker compose -f deploy/compose.yml --env-file deploy/.env up -d --build   # http://localhost
docker compose -f deploy/compose.yml --env-file deploy/.env down -v         # 정리 (데이터 삭제)
```
