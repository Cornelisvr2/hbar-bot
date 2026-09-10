From 5e2b76fc9972a2fdb345cbe55c88c85504f89ab9 Mon Sep 17 00:00:00 2001
From: Claude <claude@local>
Date: Thu, 10 Sep 2026 14:42:50 +0000
Subject: [PATCH] TTS box-guard: geen entry als de koers al door de boxrand is
 (toevoeging op het origineel)

---
 box_guard.py    | 178 ++++++++++++++++++++++++++++++++++++++++++++++++
 ibkr_web_api.py |   2 +-
 main.py         |  14 ++++
 3 files changed, 193 insertions(+), 1 deletion(-)
 create mode 100644 box_guard.py

diff --git a/box_guard.py b/box_guard.py
new file mode 100644
index 0000000..5bdc36b
--- /dev/null
+++ b/box_guard.py
@@ -0,0 +1,178 @@
+"""
+box_guard.py — Touch & Turn Scalper, Box-guard (bewuste toevoeging, 10 sep 2026)
+
+Het originele TTS-plan plaatst na de 15-minuten-openingscandle direct
+een limietorder op de High (SHORT) of Low (LONG) en gaat er
+stilzwijgend van uit dat de koers op dat moment nog BINNEN de
+openingsrange zit -- zodat de limiet pas vult als de koers terugkomt
+naar de rand ("touch"). Het plan zegt niets over de situatie waarin de
+koers in minuut 16 al door die rand heen is gebroken. Dan vult een
+SELL LMT op de High onmiddellijk, tegen de trend in, met een stop op
+een halve TP-afstand -- precies wat op 10 sep 2026 bij AAPL (SHORT
+boven de box) en META (LONG onder de box) gebeurde: beide 15:46 in,
+15:47 uit op de stop.
+
+Deze guard is een TOEVOEGING op het origineel (zelfde categorie als de
+positiegrootte en de dagstop): vóór het plaatsen van de entry-order
+wordt de actuele koers opgevraagd en moet die nog aan de "goede" kant
+van het entry-niveau liggen:
+
+    SHORT: last < opening high   (koers moet nog omhoog naar de rand)
+    LONG:  last > opening low    (koers moet nog omlaag naar de rand)
+
+Zit de koers er al doorheen, dan wordt het symbool overgeslagen met een
+duidelijke beslissingsregel op het dashboard. Is er geen koers
+beschikbaar (snapshot mislukt), dan wordt de trade NIET geblokkeerd --
+dan geldt het originele gedrag, met een waarschuwing in het log. De
+guard mag een data-hapering nooit in een stille "geen trades meer"
+laten ontaarden.
+
+LET OP: bij een VERTRAAGDE marketdata-feed is de snapshot-koers ook
+vertraagd. Dan is de guard blind voor de laatste minuten en laat hij
+(net als het origineel) gewoon door -- nooit slechter dan zonder
+guard. De datastatus (R = realtime, D = delayed) wordt daarom expliciet
+meegelogd, zodat je dit in het log kunt zien.
+
+Pure logica hier, geen IBKR-verbinding nodig om te testen (zie __main__).
+"""
+
+from __future__ import annotations
+
+import logging
+from dataclasses import dataclass
+
+logger = logging.getLogger("box_guard")
+
+
+@dataclass
+class BoxGuardResult:
+    allowed: bool
+    last_price: float | None
+    reason: str
+
+
+def check_price_inside_box(direction: str, entry_price: float, last_price: float | None,
+                           data_status: str = "?") -> BoxGuardResult:
+    """
+    Pure controle: mag de entry-limietorder geplaatst worden?
+
+    Args:
+        direction: "LONG" of "SHORT"
+        entry_price: het entry-niveau (opening Low bij LONG, opening High bij SHORT)
+        last_price: actuele koers, of None als die niet beschikbaar is
+        data_status: alleen voor de logregel ("R" realtime, "D" delayed, "?" onbekend)
+    """
+    if last_price is None or last_price <= 0:
+        return BoxGuardResult(
+            allowed=True, last_price=None,
+            reason="geen actuele koers beschikbaar -- guard overgeslagen, order volgens origineel geplaatst",
+        )
+
+    if direction == "SHORT":
+        ok = last_price < entry_price
+        kant = "onder" if ok else "op/boven"
+    elif direction == "LONG":
+        ok = last_price > entry_price
+        kant = "boven" if ok else "op/onder"
+    else:
+        return BoxGuardResult(allowed=False, last_price=last_price, reason=f"onbekende richting {direction}")
+
+    afwijking_pct = (last_price - entry_price) / entry_price * 100
+    tekst = (
+        f"koers {last_price:.2f} ligt {kant} entry-niveau {entry_price:.2f} "
+        f"({afwijking_pct:+.2f}%, data {data_status})"
+    )
+    if ok:
+        return BoxGuardResult(allowed=True, last_price=last_price, reason=f"box-guard OK: {tekst}")
+    return BoxGuardResult(
+        allowed=False, last_price=last_price,
+        reason=f"koers al door boxrand, geen touch-vanuit-de-box mogelijk -- {tekst}",
+    )
+
+
+def fetch_last_price(symbol: str) -> tuple[float | None, str]:
+    """
+    Haalt de actuele koers op via de Client Portal snapshot (veld 31 =
+    last, veld 6509 = datastatus). Geeft (koers, status) terug; koers is
+    None bij een fout. Twee aanroepen: de eerste initialiseert de
+    datastroom, de tweede levert doorgaans pas waarden.
+    """
+    try:
+        from ibkr_web_api import resolve_conid, get_market_data_snapshot
+        conid = resolve_conid(symbol)
+        if conid is None:
+            return None, "?"
+        snapshot = None
+        for _ in range(2):
+            snapshot = get_market_data_snapshot(conid)
+            if _snapshot_last(snapshot) is not None:
+                break
+            import time
+            time.sleep(1.5)
+        return _snapshot_last(snapshot), _snapshot_status(snapshot)
+    except Exception as e:
+        logger.warning(f"Box-guard: kon actuele koers niet ophalen voor {symbol}: {e}")
+        return None, "?"
+
+
+def _snapshot_record(snapshot) -> dict:
+    if isinstance(snapshot, list) and snapshot and isinstance(snapshot[0], dict):
+        return snapshot[0]
+    if isinstance(snapshot, dict):
+        return snapshot
+    return {}
+
+
+def _snapshot_last(snapshot) -> float | None:
+    """Veld 31 kan een letterprefix dragen (bv. 'C320.43' = laatste slotkoers, 'H' = halted)."""
+    raw = _snapshot_record(snapshot).get("31")
+    if raw is None:
+        return None
+    s = str(raw).strip()
+    while s and not (s[0].isdigit() or s[0] in ".-"):
+        s = s[1:]
+    try:
+        return float(s.replace(",", ""))
+    except ValueError:
+        return None
+
+
+def _snapshot_status(snapshot) -> str:
+    raw = _snapshot_record(snapshot).get("6509")
+    return str(raw).strip() if raw else "?"
+
+
+if __name__ == "__main__":
+    logging.basicConfig(level=logging.INFO)
+
+    # AAPL 10 sep 2026: SHORT op high 320.43 terwijl koers al 320.60 -> blokkeren
+    r = check_price_inside_box("SHORT", 320.43, 320.60, "R")
+    print("Scenario 1 (SHORT, koers boven high):", r.allowed, "--", r.reason)
+    assert r.allowed is False
+
+    # SHORT terwijl koers nog in de box -> toestaan
+    r = check_price_inside_box("SHORT", 320.43, 319.10, "R")
+    print("Scenario 2 (SHORT, koers in box):", r.allowed, "--", r.reason)
+    assert r.allowed is True
+
+    # META 10 sep 2026: LONG op low 647.33 terwijl koers al 646.90 -> blokkeren
+    r = check_price_inside_box("LONG", 647.33, 646.90, "R")
+    print("Scenario 3 (LONG, koers onder low):", r.allowed, "--", r.reason)
+    assert r.allowed is False
+
+    # LONG, koers in box -> toestaan
+    r = check_price_inside_box("LONG", 647.33, 648.50, "R")
+    print("Scenario 4 (LONG, koers in box):", r.allowed, "--", r.reason)
+    assert r.allowed is True
+
+    # Geen koers -> niet blokkeren (origineel gedrag)
+    r = check_price_inside_box("LONG", 647.33, None)
+    print("Scenario 5 (geen koers):", r.allowed, "--", r.reason)
+    assert r.allowed is True
+
+    # Snapshot-parsing met letterprefix
+    assert _snapshot_last([{"31": "C320.43", "6509": "DPB"}]) == 320.43
+    assert _snapshot_status([{"31": "320.43", "6509": "RpB"}]) == "RpB"
+    assert _snapshot_last([]) is None
+    print("Snapshot-parsing OK")
+    print("\nAlle scenario's OK")
diff --git a/ibkr_web_api.py b/ibkr_web_api.py
index bca59e8..7c7071f 100644
--- a/ibkr_web_api.py
+++ b/ibkr_web_api.py
@@ -295,7 +295,7 @@ def get_market_data_snapshot(conid: int) -> dict:
     try:
         response = session.get(
             f"{BASE_URL}/iserver/marketdata/snapshot",
-            params={"conids": str(conid), "fields": "31,84,86"},
+            params={"conids": str(conid), "fields": "31,84,86,6509"},  # 6509 = datastatus (R/D), voor box_guard.py
             timeout=15,
         )
         response.raise_for_status()
diff --git a/main.py b/main.py
index a23e8cd..83f8fcf 100644
--- a/main.py
+++ b/main.py
@@ -156,6 +156,20 @@ def run_symbol_cycle(symbol: str, capital: float, dry_run: bool) -> dict:
         logger.warning(reason)
         return {"status": "skipped", "symbol": symbol, "reason": reason}
 
+    # BOX-GUARD (bewuste toevoeging, 10 sep 2026 -- zie box_guard.py):
+    # het origineel neemt stilzwijgend aan dat de koers om 15:46 nog IN
+    # de openingsrange zit. Bij een uitbraak vult de limiet anders
+    # direct tegen de trend in (AAPL/META, 10 sep 2026: 15:46 in,
+    # 15:47 uit op de stop). Alleen in live-modus; bij een mislukte
+    # snapshot wordt NIET geblokkeerd (origineel gedrag blijft gelden).
+    if not dry_run:
+        from box_guard import fetch_last_price, check_price_inside_box
+        last_price, data_status = fetch_last_price(symbol)
+        guard = check_price_inside_box(signal.direction, signal.entry_price, last_price, data_status)
+        logger.info(f"Box-guard {symbol}: {guard.reason}")
+        if not guard.allowed:
+            return {"status": "skipped", "symbol": symbol, "reason": guard.reason}
+
     plan = calculate_exit_levels(signal, capital=capital)
     if plan.position_size * plan.entry_price < 5.0:
         reason = f"Positiewaarde te klein voor {symbol} met €{capital:.2f} kapitaal."
-- 
2.43.0
