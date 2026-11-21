#!/usr/bin/env bash
# 전시 대비 부하 테스트 (맥에서 실행, k6 필요: brew install k6). 새 토론(LLM 호출)은 하지 않는다.
#   ./run.sh smoke        관람객 1명 1회 (동작 확인)
#   ./run.sh load [PEAK]  최대 PEAK명 동시 (기본 30), 약 4분. 30초마다 서버 자원을 기록한다
#   ./run.sh cleanup      테스트 게스트(닉네임 k6t_*)와 퀴즈 기록 삭제. 테스트 뒤 꼭 실행 (오늘 랭킹에 보인다)
# 결과와 해석: docs/LOAD-TEST.md
set -euo pipefail
cd "$(dirname "$0")"
SERVER="${SERVER:-ubuntu@54.253.242.203}"
SSH=(ssh -i "${SSH_KEY:-$HOME/.ssh/bullbear.pem}" -o ConnectTimeout=10 "$SERVER")
PSQL='docker exec -i bullbear-postgres-1 sh -c "psql -U \$POSTGRES_USER -d \$POSTGRES_DB -At -v ON_ERROR_STOP=1"'

stats() {
	"${SSH[@]}" 'docker stats --no-stream --format "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"; uptime'
}

case "${1:-}" in
	smoke)
		k6 run -q --vus 1 --iterations 1 visitor.js
		;;
	load)
		PEAK="${2:-30}"
		echo "== 시작 전 서버"; stats
		( for i in $(seq 1 8); do sleep 30; echo "== +$((i*30))s"; stats; done ) > server-stats.txt 2>&1 &
		MON=$!
		PEAK="$PEAK" k6 run -q --summary-export "summary-$PEAK.json" visitor.js || true
		wait $MON || true
		echo "== 부하 중 서버 (server-stats.txt)"; cat server-stats.txt
		echo "== 끝나면: ./run.sh cleanup"
		;;
	cleanup)
		"${SSH[@]}" "$PSQL" <<'SQL'
begin;
create temp table t as select id from users where nickname like 'k6t\_%';
select 'test users', count(*) from t;
delete from quiz_questions where round_id in (select id from quiz_rounds where user_id in (select id from t));
delete from quiz_rounds where user_id in (select id from t);
delete from judgment_scores where judgment_id in (select id from judgments where user_id in (select id from t));
delete from judgments where user_id in (select id from t);
delete from auth_tokens where user_id in (select id from t);
delete from users where id in (select id from t);
select 'left', count(*) from users where nickname like 'k6t\_%';
commit;
SQL
		;;
	*) echo "사용법: $0 smoke | load [PEAK] | cleanup" >&2; exit 1 ;;
esac
