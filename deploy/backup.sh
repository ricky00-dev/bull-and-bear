#!/usr/bin/env bash
# DB 백업: 매일 새벽 cron으로 돌린다. 14일치를 남긴다.
#   0 4 * * * /home/ubuntu/bull-and-bear/deploy/backup.sh >> /home/ubuntu/backup.log 2>&1
# 복구는 deploy/restore.sh
set -euo pipefail
cd "$(dirname "$0")"
ENV_FILE="${ENV_FILE:-.env}"
DIR="${BACKUP_DIR:-$HOME/backups}"
mkdir -p "$DIR"
FILE="$DIR/bullbear-$(date +%Y%m%d-%H%M).sql.gz"
# 실패하면 빈 파일이 남지 않게 임시 파일에 받고 옮긴다
docker compose -f compose.yml --env-file "$ENV_FILE" exec -T postgres pg_dump -U bullbear --clean --if-exists bullbear | gzip > "$FILE.tmp"
mv "$FILE.tmp" "$FILE"
find "$DIR" -name 'bullbear-*.sql.gz' -mtime +14 -delete
echo "백업 완료: $FILE ($(du -h "$FILE" | cut -f1))"
