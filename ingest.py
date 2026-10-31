#!/usr/bin/env python3
"""Turn raw browser-scraped rows (see REFRESH.md) into cache/<source>.json for fetch.py.

usage: python3 ingest.py usfa raw.json   (rows: [state, "NOV 07", "07/18" or "", name, ages, location, fee, tid])
       python3 ingest.py usfa_teams raw.txt   (lines: T|tid|division|team|class  or  V|tid|ballpark|address)
PGF no longer needs this: fetch.py reads TournamentConnect's API directly (pgf.py).
"""
import datetime as dt, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import fetch as f

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


def usfa_teams(text):
    """USFA "Who's Playing" lists -> cache/usfa_teams.json {tid: {"divisions", "venues"}} for teams.py."""
    out = {}
    for line in text.splitlines():
        p = line.split("|")
        if len(p) < 4:
            continue
        e = out.setdefault("USFA" + p[1], {"divisions": [], "venues": []})
        if p[0] == "V":
            e["venues"].append({"name": p[2], "address": p[3]})
        elif len(p) >= 5:
            cls = p[4]
            if re.fullmatch(r"\d*", cls) or cls in ("Accepted", "Pay Later"):  # points or payment status, not a class
                cls = ""
            cls = "waitlist" if cls == "Wait List" else cls
            divs = e["divisions"]
            if not divs or divs[-1]["name"] != p[2]:
                divs.append({"name": p[2], "teams": []})
            divs[-1]["teams"].append([p[3], "", "", cls])
    return out


if __name__ == "__main__":
    kind, path = sys.argv[1], sys.argv[2]
    if kind == "usfa_teams":
        teams = usfa_teams(open(path).read())
        if not teams:
            sys.exit("usfa_teams: nothing parsed, cache left unchanged")
        (ROOT / "cache" / "usfa_teams.json").write_text(json.dumps(teams, separators=(",", ":"), ensure_ascii=False))
        sys.exit(print(f"usfa_teams: {len(teams)} tournaments, {sum(len(d['teams']) for v in teams.values() for d in v['divisions'])} teams"))
    rows = {"usfa": usfa}[kind](json.load(open(path)))
    if not rows:
        sys.exit(f"{kind}: no rows parsed, cache left unchanged")
    now = dt.datetime.now().astimezone().isoformat(timespec="minutes")
    (ROOT / "cache" / f"{kind}.json").write_text(json.dumps({"updated": now, "events": rows}))
    print(f"{kind}: {len(rows)} events cached")
