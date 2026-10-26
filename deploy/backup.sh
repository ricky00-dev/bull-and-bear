#!/usr/bin/env bash
# DB 백업: 매일 새벽 cron으로 돌린다. 14일치를 남긴다.
#   0 4 * * * /home/ubuntu/bull-and-bear/deploy/backup.sh >> /home/ubuntu/backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"
DIR="${BACKUP_DIR:-$HOME/backups}"
mkdir -p "$DIR"
FILE="$DIR/bullbear-$(date +%Y%m%d-%H%M).sql.gz"
docker compose -f compose.yml --env-file .env exec -T postgres pg_dump -U bullbear bullbear | gzip > "$FILE"
find "$DIR" -name 'bullbear-*.sql.gz' -mtime +14 -delete
echo "백업 완료: $FILE ($(du -h "$FILE" | cut -f1))"
