#!/usr/bin/env python3
"""(8 sep 2026) Samenvatting van logs/decisions.jsonl voor het afstellen
van drempels. Gebruik: python3 analyse_decisions.py [logs/decisions.jsonl]"""
import sys, json, collections, datetime
path = sys.argv[1] if len(sys.argv) > 1 else "logs/decisions.jsonl"
rows = []
try:
    with open(path) as f:
        rows = [json.loads(l) for l in f if l.strip()]
except FileNotFoundError:
    print("geen log gevonden:", path); sys.exit(0)
if not rows:
    print("log is leeg"); sys.exit(0)
fmt = lambda ts: datetime.datetime.fromtimestamp(ts).strftime("%d-%m %H:%M")
print(f"{len(rows)} regels, {fmt(rows[0]['ts'])} t/m {fmt(rows[-1]['ts'])}\n")
by = collections.Counter(r["kind"] + ("/" + r["subkind"] if r.get("subkind") else "") for r in rows)
for k, n in by.most_common():
    print(f"{n:5d}  {k}")
print("\nBeslissingen (geen near-miss):")
for r in rows:
    if r["kind"] == "near_miss":
        continue
    extra = {k: v for k, v in r.items() if k not in ("ts", "kind")}
    print(f"  {fmt(r['ts'])}  {r['kind']:22s} " + ", ".join(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}" for k, v in extra.items()))
nm = [r for r in rows if r["kind"] == "near_miss"]
if nm:
    print(f"\nNear-misses ({len(nm)}), laatste 15:")
    for r in nm[-15:]:
        extra = {k: v for k, v in r.items() if k not in ("ts", "kind", "subkind")}
        print(f"  {fmt(r['ts'])}  {r['subkind']:24s} " + ", ".join(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}" for k, v in extra.items()))
