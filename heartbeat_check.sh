#!/bin/bash
# (8 sep 2026) Heartbeat-bewaking van de HBAR-bot. Elke 5 min via cron.
# Alarmeert via Telegram als (a) de container niet draait of (b) het
# statusbestand ouder is dan MAX_AGE seconden (lus hangt). Herhaalt een
# alarm hoogstens elke 30 min; meldt herstel eenmalig.
cd /root/hbar_bot || exit 1
set -a; source .env; set +a
STATE=/root/hbar_bot/logs/bot_state.json
FLAG=/root/hbar_bot/logs/.heartbeat_alarm
MAX_AGE=${HEARTBEAT_MAX_AGE:-600}
now=$(date +%s)

reason=""
if ! docker compose ps --status running --services 2>/dev/null | grep -qx hbar-bot; then
  reason="container hbar-bot draait niet"
elif [ ! -f "$STATE" ]; then
  reason="statusbestand ontbreekt"
else
  age=$(( now - $(stat -c %Y "$STATE") ))
  [ "$age" -gt "$MAX_AGE" ] && reason="laatste cyclus ${age}s geleden (> ${MAX_AGE}s) -- lus hangt?"
fi

send() {
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d chat_id="${TELEGRAM_CHAT_ID}" -d text="$1" >/dev/null
}

if [ -n "$reason" ]; then
  last=0; [ -f "$FLAG" ] && last=$(cat "$FLAG")
  if [ $(( now - last )) -gt 1800 ]; then
    send "🚨 HBAR Bot HEARTBEAT: $reason"
    echo "$now" > "$FLAG"
  fi
  echo "$(date '+%F %T') ALARM: $reason"
elif [ -f "$FLAG" ]; then
  rm -f "$FLAG"
  send "✅ HBAR Bot HEARTBEAT: hersteld, bot draait weer normaal."
  echo "$(date '+%F %T') hersteld"
fi
