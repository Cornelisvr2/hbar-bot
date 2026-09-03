#!/bin/bash
# daily_status_cron.sh -- bedoeld om dagelijks om 09:00 te draaien via crontab.
#
# Installeren (op de VPS, in de hbar_bot-map):
#   chmod +x daily_status_cron.sh
#   crontab -e
# Voeg toe (draait elke dag om 09:00):
#   0 9 * * * /root/hbar_bot/daily_status_cron.sh >> /root/hbar_bot/logs/daily_status.log 2>&1

set -e
cd "$(dirname "$0")"

echo "=== Dagelijks statusrapport: $(date) ==="

docker compose exec -T hbar-bot python3 daily_status_report.py

echo "=== Klaar: $(date) ==="
