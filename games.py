#!/usr/bin/env python3
"""Pool play and brackets for tournaments Shelby Steel is registered in.

Reads site/ours.json and site/data.json; writes site/games/<event id>.json plus site/games/index.json.
Runs from the game-day GitHub workflow every 15 minutes Thu–Sun; exits quickly when nothing is in its window.
USSSA is supported now (Game Center API); other sanctions link out until added.
"""
import datetime as dt, json, re, subprocess, sys, urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import venues

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
OUT = SITE / "games"
TODAY = dt.date.today()
WINDOW_BEFORE, WINDOW_AFTER = 14, 1  # start checking 2 weeks out so pools show the moment they post; keep refreshing through the day after it ends


def post(data):
    r = subprocess.run(["curl", "-sL", "--max-time", "40", "-A", "Mozilla/5.0 (Macintosh) ShelbySteelFinder",
                        "--data", urllib.parse.urlencode(data), "https://www.usssa.com/api/"],
                       capture_output=True, text=True).stdout
    try:
        return json.loads(r)
    except ValueError:
        return {}


def get(url):
    return subprocess.run(["curl", "-sL", "--max-time", "40", "-A", "Mozilla/5.0 (Macintosh) ShelbySteelFinder", url],
                          capture_output=True, text=True).stdout


def clean_bracket(html, style):
    """USSSA sends bracket markup; keep layout, drop anything active. Shown in a sandboxed iframe."""
    html = re.sub(r"<script.*?</script>", "", html or "", flags=re.S | re.I)
    html = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", html, flags=re.I)
    html = re.sub(r"(href|src)\s*=\s*([\"'])\s*javascript:[^\"']*\2", "", html, flags=re.I)
    style = re.sub(r"@import[^;]+;|expression\([^)]*\)|url\([^)]*\)", "", style or "", flags=re.I)
    return html, style


def usssa_games(ev, ages):
    page = get(ev["url"])
    m = re.search(r"event_gameCenter/\?eventID=(\d+)", page)
    if not m:
        return None
    eid = m.group(1)
    menu = post({"action": "selpV2", "eventID": eid, "divisionID": "", "tabName": "gameCenter"})
    divisions = []
    for div in menu.get("gameCenterDDown") or []:
        if ages and int(div.get("age") or 0) not in ages:
            continue
        out = {"name": f"{div.get('age')}U {div.get('Class', '')}".strip(), "pools": [], "brackets": []}
        for o in div.get("options") or []:
            if o.get("optionID") == "results":
                continue
            gm = {"eventID": eid, "divisionID": str(o["divisionID"]), "bnp": str(o["bracketNotPool"]),
                  "bf": str(o["bracketFlight"]), "option": str(o["optionID"]), "isWinner": str(o["isWinner"])}
            data = post({"action": "getGameCenterContent", "gmParams": json.dumps(gm, separators=(",", ":"))})
            if not data.get("released"):
                continue
            if data.get("template") == "schedule":
                for p in data.get("pools") or []:
                    games = [{
                        "time": g.get("the_datetime"), "field": g.get("fieldName") or "", "game": g.get("gameNumber"),
                        "a": g.get("winningTeam") or "", "b": g.get("losingTeam") or "",
                        "as": g.get("winnersScore"), "bs": g.get("losersScore"),
                        "aClass": g.get("winningTeamClass") or "", "bClass": g.get("losingTeamClass") or "",
                    } for g in p.get("schedules") or []]
                    out["pools"].append({"name": f"Pool {p.get('pool')}", "final": bool(p.get("isFinal")), "games": games})
            elif data.get("template") == "bracket" and data.get("html"):
                html, style = clean_bracket(data["html"], data.get("style"))
                out["brackets"].append({"name": o.get("name") + (f" ({o['format']})" if o.get("format") else ""),
                                        "html": html, "style": style})
        if out["pools"] or out["brackets"]:
            divisions.append(out)
    return {"source": f"https://www.usssa.com/fastpitch/event_gameCenter/?eventID={eid}", "divisions": divisions,
            "venues": venues.usssa(page)}


READERS = {"USSSA": usssa_games}


def main():
    ours = json.loads((SITE / "ours.json").read_text())
    OUT.mkdir(exist_ok=True)
    index_path = OUT / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    lo, hi = (TODAY - dt.timedelta(days=WINDOW_AFTER)).isoformat(), (TODAY + dt.timedelta(days=WINDOW_BEFORE)).isoformat()
    wanted = {}
    for r in ours.get("registrations", []):
        if r.get("eventId") and r.get("sanction") in READERS and r["start"] <= hi and (r.get("end") or r["start"]) >= lo:
            w = wanted.setdefault(r["eventId"], {"ev": r, "ages": set()})
            age = re.match(r"(\d+)U", r.get("team") or "")
            if age:
                w["ages"].add(int(age.group(1)))
    if not wanted:
        print("no Shelby Steel tournaments in the game-day window", file=sys.stderr)
    for eid, w in wanted.items():
        try:
            result = READERS[w["ev"]["sanction"]](w["ev"], w["ages"])
        except Exception as exc:
            print(f"{w['ev']['name']}: {exc}", file=sys.stderr)
            continue
        if not result:
            continue
        result["updated"] = now
        (OUT / f"{eid}.json").write_text(json.dumps(result, separators=(",", ":")))
        index[eid] = {"updated": now, "name": w["ev"]["name"], "pools": sum(len(d["pools"]) for d in result["divisions"]),
                      "brackets": sum(len(d["brackets"]) for d in result["divisions"])}
        print(f"{w['ev']['name']}: {index[eid]}", file=sys.stderr)
    cutoff = (TODAY - dt.timedelta(days=7)).isoformat()  # drop old events from the index after a week
    keep = {e["eventId"] for e in ours.get("registrations", []) if e.get("eventId") and (e.get("end") or e["start"]) >= cutoff}
    index = {k: v for k, v in index.items() if k in keep}
    index_path.write_text(json.dumps(index, separators=(",", ":")))


if __name__ == "__main__":
    main()
