#!/usr/bin/env python3
"""Pool play (with standings/seeding), brackets and final results for tournaments Shelby Steel is registered in.

Reads site/ours.json and site/data.json; writes site/games/<event id>.json plus site/games/index.json.
Runs from the game-day GitHub workflow every 15 minutes Thu–Sun; exits quickly when nothing is in its window.
USSSA (Game Center API) and MVP (iTournamentBrackets) are supported; other sanctions link out until added.
"""
import datetime as dt, json, re, subprocess, sys, urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mvp, venues

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
    html = re.sub(r"<br>\s*Pub\d+-\d+-D[\d.]+T[\d:]+\s*(?=<br>)", "", html)  # USSSA's publish stamp changes on every fetch
    style = re.sub(r"@import[^;]+;|expression\([^)]*\)|url\([^)]*\)", "", style or "", flags=re.I)
    return html, style


def standings_from_games(games):
    """W-L-T and runs for each team from posted pool scores, best first: win %, fewest runs allowed, run difference.
    Directors break ties their own way (often head-to-head first), so this is marked as calculated, not official."""
    t = {}
    for g in games:
        if g.get("as") in (None, "") or g.get("bs") in (None, ""):
            continue
        try:
            a, b = int(g["as"]), int(g["bs"])
        except (TypeError, ValueError):
            continue
        for team, f, ag in ((g["a"], a, b), (g["b"], b, a)):
            r = t.setdefault(team, {"team": team, "w": 0, "l": 0, "t": 0, "rs": 0, "ra": 0})
            r["w" if f > ag else "l" if f < ag else "t"] += 1
            r["rs"] += f
            r["ra"] += ag
    rows = list(t.values())
    for r in rows:
        r["rd"] = r["rs"] - r["ra"]
    pct = lambda r: (r["w"] + r["t"] / 2) / max(1, r["w"] + r["l"] + r["t"])
    return sorted(rows, key=lambda r: (-pct(r), r["ra"], -r["rd"]))


def usssa_standings(pool):
    """USSSA's own pool standings once results are in; before that its order is the pre-game seeding."""
    rows = [{"team": r.get("teamName") or "", "w": r.get("pool_wins") or 0, "l": r.get("pool_loses") or 0,
             "t": r.get("pool_ties") or 0, "ra": r.get("pool_avg_points_allowed"), "rd": r.get("pool_avg_point_diff_with_maximum"),
             "place": r.get("poolPlace")} for r in sorted(pool.get("results") or [], key=lambda r: r.get("poolPlace") or 99)]
    if any(r["w"] or r["l"] or r["t"] for r in rows):
        return rows, "official"
    return rows, "seeding"


def usssa_games(ev, ages):
    page = get(ev["url"])
    m = re.search(r"event_gameCenter/\?eventID=(\d+)", page)
    if not m:
        return None
    eid = m.group(1)
    menu = post({"action": "selpV2", "eventID": eid, "divisionID": "", "tabName": "gameCenter"})
    divisions = []
    for div in menu.get("gameCenterDDown") or []:
        age = str(div.get("age") or "")
        if ages and (int(age) if age.isdigit() else 18) not in ages:  # "HS" divisions count as 18U
            continue
        out = {"name": f"{div.get('age')}U {div.get('Class', '')}".strip(), "pools": [], "brackets": []}
        for o in div.get("options") or []:
            if o.get("optionID") == "results":
                rep = post({"action": "getGameCenterContent", "gmParams": json.dumps(
                    {"eventID": eid, "divisionID": str(o["divisionID"]), "bnp": "0", "bf": "0", "option": "results",
                     "isWinner": "0"}, separators=(",", ":"))})
                places = [{"place": r.get("place"), "team": r.get("teamname") or "", "w": r.get("wins") or 0, "l": r.get("loses") or 0}
                          for r in rep.get("tournamentResults") or [] if r.get("place")]
                if rep.get("released") and places:
                    out["results"] = sorted(places, key=lambda r: r["place"])
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
                    rows, kind = usssa_standings(p)
                    if kind == "seeding" and any(g["as"] is not None for g in games):
                        rows, kind = standings_from_games(games), "calculated"
                    out["pools"].append({"name": f"Pool {p.get('pool')}", "final": bool(p.get("isFinal")), "games": games,
                                         "standings": rows, "standingsKind": kind})
            elif data.get("template") == "bracket" and data.get("html"):
                html, style = clean_bracket(data["html"], data.get("style"))
                out["brackets"].append({"name": o.get("name") + (f" ({o['format']})" if o.get("format") else ""),
                                        "html": html, "style": style})
        if out["pools"] or out["brackets"] or out.get("results"):
            divisions.append(out)
    return {"source": f"https://www.usssa.com/fastpitch/event_gameCenter/?eventID={eid}", "divisions": divisions,
            "venues": venues.usssa(page)}


def mvp_games(ev, ages):
    """MVP posts per-age links to iTournamentBrackets: a pool schedule and an elimination bracket."""
    page = get(ev["url"])
    divisions = []
    for label, pool_url, bracket_url in mvp.links(page):
        age = re.match(r"(\d{1,2})", label)
        if ages and age and int(age.group(1)) not in ages:
            continue
        out = {"name": label, "pools": [], "brackets": []}
        if pool_url:
            games, rows = mvp.pool_games(pool_url, ev["start"][:4])
            if games or rows:
                out["pools"].append({"name": "Pool play", "final": False, "games": games,
                                     "standings": rows or standings_from_games(games), "standingsKind": "official" if rows else "calculated"})
        if bracket_url:
            head, body = mvp.bracket(bracket_url)
            if "Seed" in body or "Game" in body:
                html, _ = clean_bracket(head + body, "")
                out["brackets"].append({"name": "Elimination bracket", "html": html, "style": ""})
        if out["pools"] or out["brackets"]:
            divisions.append(out)
    return {"source": ev["url"], "divisions": divisions, "venues": mvp.venues(page)}


READERS = {"USSSA": usssa_games, "MVP": mvp_games}


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
        path = OUT / f"{eid}.json"
        before = json.loads(path.read_text()) if path.exists() else {}
        if {k: v for k, v in before.items() if k != "updated"} == result and eid in index:
            continue  # nothing new; leave the files alone so the Mac and GitHub only push real changes
        result["updated"] = now
        path.write_text(json.dumps(result, separators=(",", ":")))
        ev = w["ev"]
        index[eid] = {"updated": now, "name": ev["name"], "pools": sum(len(d["pools"]) for d in result["divisions"]),
                      "brackets": sum(len(d["brackets"]) for d in result["divisions"]),
                      "sanction": ev.get("sanction"), "start": ev["start"], "end": ev.get("end") or ev["start"],
                      "city": ev.get("city"), "state": ev.get("state"), "url": ev.get("url"),
                      "teams": sorted({r["team"] for r in ours["registrations"] if r.get("eventId") == eid and r.get("team")})}
        print(f"{w['ev']['name']}: {index[eid]}", file=sys.stderr)
    cutoff = (TODAY - dt.timedelta(days=7)).isoformat()  # drop old events from the index after a week
    keep = {e["eventId"] for e in ours.get("registrations", []) if e.get("eventId")}
    index = {k: v for k, v in index.items() if k in keep or (v.get("end") or "") >= cutoff}  # last weekend stays a week
    index_path.write_text(json.dumps(index, separators=(",", ":")))


if __name__ == "__main__":
    main()
