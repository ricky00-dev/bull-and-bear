#!/usr/bin/env bash
# 백업 파일로 DB를 되돌린다. 지금 DB 내용은 백업 시점으로 덮어써진다.
#   deploy/restore.sh ~/backups/bullbear-20261110-0400.sql.gz
# API를 멈추고 복구한 뒤 다시 켠다 (복구 중 쓰기가 섞이지 않게).
set -euo pipefail
FILE="${1:?복구할 백업 파일을 지정하세요}"
[ -f "$FILE" ] || { echo "파일 없음: $FILE"; exit 1; }
FILE="$(cd "$(dirname "$FILE")" && pwd)/$(basename "$FILE")"
cd "$(dirname "$0")"
ENV_FILE="${ENV_FILE:-.env}"
DC=(docker compose -f compose.yml --env-file "$ENV_FILE")

if [ "${YES:-}" != "1" ]; then
  read -r -p "현재 DB를 $(basename "$FILE") 시점으로 덮어씁니다. 계속할까요? (yes) " answer
  [ "$answer" = "yes" ] || { echo "취소"; exit 1; }
fi

"${DC[@]}" stop api
gunzip -c "$FILE" | "${DC[@]}" exec -T postgres psql -U bullbear -d bullbear -v ON_ERROR_STOP=1 -q
"${DC[@]}" start api
echo "복구 완료: $(basename "$FILE")"
