#!/bin/bash
# recalibrate_cron.sh -- bedoeld om periodiek te draaien via crontab.
#
# Installeren (op de VPS, in de hbar_bot-map):
#   chmod +x recalibrate_cron.sh
#   crontab -e
# Voeg toe (draait elke dag om 03:00):
#   0 3 * * * /root/hbar_bot/recalibrate_cron.sh >> /root/hbar_bot/logs/recalibrate.log 2>&1

set -e
cd "$(dirname "$0")"

echo "=== Herkalibratie gestart: $(date) ==="

BEFORE=$(cat calibration_examples.json 2>/dev/null || echo "[]")

docker compose exec -T hbar-bot python3 recalibrate_from_live_history.py

AFTER=$(cat calibration_examples.json 2>/dev/null || echo "[]")

if [ "$BEFORE" != "$AFTER" ]; then
    echo "Nieuwe kalibratie gevonden -- bot herstarten om toe te passen."
    docker compose restart hbar-bot
else
    echo "Geen wijziging in kalibratie -- geen herstart nodig."
fi

echo "=== Database-opschoning (Gemini-feedback, 23 aug 2026) ==="
docker compose exec -T database psql -U hbar_bot -d hbar_bot -c "SELECT * FROM cleanup_old_data(30);"

echo "=== Herkalibratie voltooid: $(date) ==="
