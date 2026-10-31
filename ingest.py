#!/usr/bin/env python3
"""Turn raw browser-scraped rows (see REFRESH.md) into cache/<source>.json for fetch.py.

usage: python3 ingest.py usfa raw.json   (rows: [state, "NOV 07", "07/18" or "", name, ages, location, fee, tid])
       python3 ingest.py pgf  raw.json   (rows: ["Nov 6 - 8, 2026", name, ages, location, fee])
"""
import datetime as dt, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import fetch as f

PGF_URL = "https://softball.tournamentconnect.premiergirlsfastpitch.com/events/register/tournaments/provider/premiergirlsfastpitch"


def usfa(rows):
    out = []
    for st, d, end, name, ages, loc, fee, tid in rows:
        s, _ = f.parse_dates(d)
        if not s:
            continue
        e = s
        if end:
            m, dd = map(int, end.split("/"))
            e = dt.date(int(s[:4]) + (1 if m < int(s[5:7]) else 0), m, dd).isoformat()
        out.append(f.event("USFA", name, s, e, f.state_of(loc, st), loc, ages, fee,
                           f"https://softball.sincsports.com/TTIntro.aspx?tid={tid}"))
    return out


def pgf(rows):
    out = []
    for d, name, ages, loc, fee in rows:
        s, e = f.parse_dates(d)
        st = f.state_of(loc)
        if s and st:
            out.append(f.event("PGF", name, s, e, st, loc, ages.replace(" Girls", ""), fee, PGF_URL))
    return out


if __name__ == "__main__":
    kind, path = sys.argv[1], sys.argv[2]
    rows = {"usfa": usfa, "pgf": pgf}[kind](json.load(open(path)))
    if not rows:
        sys.exit(f"{kind}: no rows parsed, cache left unchanged")
    now = dt.datetime.now().astimezone().isoformat(timespec="minutes")
    (ROOT / "cache" / f"{kind}.json").write_text(json.dumps({"updated": now, "events": rows}))
    print(f"{kind}: {len(rows)} events cached")
