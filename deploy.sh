#!/bin/bash
# deploy.sh -- eenmalig uit te voeren op de VPS na het uitpakken van het archief.
#
# Gebruik:
#   1. Zip het project (zie instructies in de chat) en zet 'm op de VPS,
#      bijvoorbeeld via scp:
#        scp hbar_bot.zip gebruiker@je-vps-ip:/opt/
#   2. SSH naar de VPS, ga naar /opt, unzip hbar_bot.zip
#   3. cd hbar_bot && chmod +x deploy.sh && ./deploy.sh

set -e  # stop bij de eerste fout, niet doorgaan met een half-werkende setup

echo "=== HBAR Bot deployment ==="

# 1. Logmap aanmaken (execute_hbar_swap_standalone.py en andere scripts
#    schrijven hierheen)
mkdir -p logs
echo "[1/5] Logmap aangemaakt."

# 2. .env aanmaken vanuit het voorbeeld, als die nog niet bestaat
if [ ! -f .env ]; then
    cp .env.example .env
    echo "[2/5] .env aangemaakt vanuit .env.example -- VUL DEZE NU HANDMATIG IN."
    echo "      Nooit .env committen naar git of delen."
else
    echo "[2/5] .env bestaat al, niet overschreven."
fi

# 3. Python-dependencies (voor het geval je NIET via Docker draait, maar
#    direct op de VPS -- bij Docker-gebruik doet de Dockerfile dit al)
if command -v python3 &> /dev/null; then
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
    echo "[3/5] Python-venv aangemaakt en dependencies geinstalleerd."
else
    echo "[3/5] WAARSCHUWING: python3 niet gevonden, sla dependency-installatie over."
fi

# 4. Structuur-check: alle kernbestanden aanwezig?
REQUIRED_FILES=(
    "main_orchestrator.py" "risk_manager.py" "postgres_client.py"
    "strategy_engine.py" "safety_override.py" "position_planner.py"
    "lp_manager.py" "swap_executor.py" "swap_executor_v2.py"
    "hedera_rpc_client.py" "config.py" "telegram_notify.py"
)
MISSING=0
for f in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$f" ]; then
        echo "  ONTBREEKT: $f"
        MISSING=1
    fi
done
if [ "$MISSING" -eq 0 ]; then
    echo "[4/5] Alle kernbestanden aanwezig."
else
    echo "[4/5] WAARSCHUWING: er ontbreken bestanden, zie hierboven."
fi

# 5. Verify-setup draaien (read-only, geen transacties/kosten) als .env
#    al is ingevuld
echo "[5/5] Klaar. Volgende stappen:"
echo "      1. Vul .env volledig in (zie de checklist in BOUWPLAN.md)"
echo "      2. Test met: source venv/bin/activate && python3 verify_setup.py"
echo "      3. Start (Docker): docker-compose up -d --build"
echo "         Start (direct):  python3 main_orchestrator.py"
