
Factory: 0x00000000000000000000000000000000003c3951
WHBAR: 0x0000000000000000000000000000000000163B5a
USDC: 0x000000000000000000000000000000000006f89a
Fee-tier (uit LP_FEE_TIER): 1500

Daadwerkelijke, on-chain pool-prijs (1 HBAR in USDC): 0.077454
root@srv1428932:~/hbar_bot# docker compose run --rm hbar-bot python3 -u check_position_76712.py
WARN[0000] /root/hbar_bot/docker-compose.yml: the attribute `version` is obsolete, it will be ignored, please remove it to avoid potential confusion
[+]  1/1t 1/11
 ✔ Container hbar_bot-database-1 Running                                                                            0.0s
Container hbar_bot-database-1 Waiting
Container hbar_bot-database-1 Healthy
Container hbar_bot-hbar-bot-run-bc50c5120264 Creating
Container hbar_bot-hbar-bot-run-bc50c5120264 Created
Positie 76712 on-chain: tick_lower=0, tick_upper=0, liquidity=0

lp.config.token0: 0x000000000000000000000000000000000006f89a
lp.config.token1: 0x0000000000000000000000000000000000163B5a

Werkelijke, correcte prijs NU (met dezelfde config-parameters): 129134.78978190898
root@srv1428932:~/hbar_bot#
