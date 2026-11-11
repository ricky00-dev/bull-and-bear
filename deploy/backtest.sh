#!/usr/bin/env bash
# 백테스트 시작·진행 확인 (서버에서 실행). /ops/backtest는 밖으로 열려 있지 않아 api 컨테이너 안에서 부른다
#   ./backtest.sh status
#   ./backtest.sh start 005930,000660 2026-09-01,2026-09-08
# 같은 요청을 다시 보내면 이미 돈 칸은 재사용하고 실패한 칸만 새로 돈다. 비용은 하루 BACKTEST_DAILY_USD까지
set -euo pipefail
cd "$(dirname "$0")"
ENV_FILE="${ENV_FILE:-.env}"
DC=(docker compose -f compose.yml --env-file "$ENV_FILE")

call() { # $1 메서드, $2 본문(없으면 빈 문자열)
	"${DC[@]}" exec -T api bash -c 'exec 3<>/dev/tcp/localhost/8080
printf "%s /ops/backtest HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: %s\r\n\r\n%s" "$1" "${#2}" "$2" >&3
tail -n 1 <&3' _ "$1" "$2"
	echo
}

case "${1:-status}" in
	status) call GET "" ;;
	start)
		tickers=$(echo "$2" | sed 's/[^,][^,]*/"&"/g')
		dates=$(echo "$3" | sed 's/[^,][^,]*/"&"/g')
		call POST "{\"tickers\":[$tickers],\"dates\":[$dates]}"
		;;
	*) echo "사용법: $0 status | start <종목,종목> <날짜,날짜>" >&2; exit 1 ;;
esac
