#!/usr/bin/env bash
# 운영 상태 한눈에: 컨테이너, 상태 확인, 디스크·메모리, 오늘 토론·비용, 마지막 백업
set -uo pipefail
cd "$(dirname "$0")"
ENV_FILE="${ENV_FILE:-.env}"
DC=(docker compose -f compose.yml --env-file "$ENV_FILE")
psql() { "${DC[@]}" exec -T postgres psql -U bullbear -d bullbear "$@"; }

echo "== 컨테이너"
"${DC[@]}" ps --format 'table {{.Service}}\t{{.Status}}'
echo; echo "== 상태 확인 (/healthz)"
"${DC[@]}" exec -T api bash -c 'exec 3<>/dev/tcp/localhost/8080 && printf "GET /ops/health HTTP/1.0\r\n\r\n" >&3 && tail -n 1 <&3'; echo
echo; echo "== 디스크·메모리"
df -h / | tail -n 1
free -m | awk 'NR<=3'
echo; echo "== 오늘 토론 (출처·상태별 건수, 비용 USD)"
psql -c "select origin, status, count(*), round(sum(cost_usd), 3) as usd from debates where debate_day = (now() at time zone 'Asia/Seoul')::date group by 1, 2 order by 1, 2"
echo "== 오늘 판정·퀴즈"
psql -tAc "select '판정 ' || count(*) from judgments where (created_at at time zone 'Asia/Seoul')::date = (now() at time zone 'Asia/Seoul')::date"
psql -tAc "select '퀴즈 답 ' || count(*) from quiz_questions where (answered_at at time zone 'Asia/Seoul')::date = (now() at time zone 'Asia/Seoul')::date"
echo; echo "== 마지막 백업"
ls -t "${BACKUP_DIR:-$HOME/backups}"/bullbear-*.sql.gz 2>/dev/null | head -n 1 | xargs -r ls -lh || echo "백업 없음"
