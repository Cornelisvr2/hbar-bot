#!/bin/bash
# (8 sep 2026) Dagelijkse Postgres-backup buiten Docker, 14 dagen bewaard.
cd /root/hbar_bot || exit 1
DIR=/root/hbar_bot_backups
mkdir -p "$DIR"
f="$DIR/hbar_bot_$(date +%F).sql.gz"
if docker compose exec -T database pg_dump -U hbar_bot hbar_bot | gzip > "$f"; then
  echo "$(date '+%F %T') backup ok: $f ($(du -h "$f" | cut -f1))"
else
  echo "$(date '+%F %T') backup MISLUKT"; rm -f "$f"; exit 1
fi
find "$DIR" -name 'hbar_bot_*.sql.gz' -mtime +14 -delete
