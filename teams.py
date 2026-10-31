#!/usr/bin/env python3
"""Pull registered-team lists ("Who's coming") and find Shelby Steel's registrations.

Reads site/data.json (from fetch.py) and registrations.json, writes:
  site/coming.json  {event id: {"divisions": [{"name", "teams": [[team, city, record]]}]}}
  site/ours.json    {"teams": [...], "registrations": [...]}  auto-detected + manual entries
Team lists come from USSSA, Grand Slam, Perfect Game, USA Softball and NSA (when the director releases them).
Each team row is [team, city, record, class].
"""
import datetime as dt, html, json, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import venues

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
TODAY = dt.date.today()
LOOKAHEAD_DAYS = 150
VENUES = {}  # event id -> ballparks, filled while reading USSSA event pages
STATS = {}  # host -> {"ok", "throttled", "failed"}  # written to site/status.json so refresh health is visible


def curl(url, data=None, jar=None):
    """Polite fetch: if a site answers 429 (too many requests), wait and retry a couple of times."""
    cmd = ["curl", "-sL", "--max-time", "40", "-A", "Mozilla/5.0 (Macintosh) ShelbySteelFinder", "-w", "\n%{http_code}"]
    if jar:
        cmd += ["-b", jar, "-c", jar]
    if data:
        cmd += ["--data", data]
    for wait in (0, 8, 25):
        time.sleep(wait)
        body, _, code = subprocess.run(cmd + [url], capture_output=True, text=True).stdout.rpartition("\n")
        host = STATS.setdefault(re.sub(r"^https?://([^/]+).*", r"\1", url), {"ok": 0, "throttled": 0, "failed": 0})
        if code != "429":
            host["ok" if code.startswith("2") else "failed"] += 1
            if not code.startswith("2"):
                host["lastCode"] = code
            return body
    host["throttled"] += 1
    return ""


def cells(row):
    return [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]


def usssa_coming(ev):
    """Event page carries a nonce and the USSSA event id; the team list comes from admin-ajax."""
    jar = f"/tmp/ssf-{ev['id']}.jar"
    page = curl(ev["url"], jar=jar)
    if page:
        VENUES[ev["id"]] = venues.usssa(page)  # same page lists the ballparks; no extra request
    nonce = re.search(r'script_parameter\s*=\s*\{[^}]*"nonce":"([^"]+)"', page)
    eid = re.search(r'who-coming-api[^>]*data-event-id="(\d+)"|data-event-id="(\d+)"[^>]*who-coming-api', page)
    if not (nonce and eid):
        return None
    host = re.match(r"https://[^/]+", ev["url"]).group(0)
    raw = curl(f"{host}/wp-admin/admin-ajax.php", jar=jar,
               data=f"action=fetch_who_is_coming_api_ajax&nonce={nonce.group(1)}&event_id={eid.group(1) or eid.group(2)}")
    try:
        body = json.loads(raw).get("teams_htmls", "")
    except ValueError:
        return None
    divisions, current = [], None
    for chunk in re.split(r"(<h\d[^>]*>.*?</h\d>|<tr[^>]*>.*?</tr>)", body, flags=re.S):
        if re.match(r"<h\d", chunk or ""):
            current = {"name": re.sub(r"\s*-\s*Teams\s*$", "", re.sub(r"<[^>]+>", "", html.unescape(chunk))).strip(), "teams": []}
            divisions.append(current)
        elif re.match(r"<tr", chunk or "") and current is not None:
            c = cells(chunk)
            if len(c) >= 3 and c[1] and c[1] != "Team Name":
                record = c[-1] if re.match(r"^\d+-\d+", c[-1]) else ""
                current["teams"].append([c[1], c[2], record, c[0]])
    return [d for d in divisions if d["teams"]]


def grand_slam_coming(ev):
    page = curl(ev["url"].replace("/Events/Details/", "/Events/Teams/"))
    divisions = []
    for part in re.split(r'(?=<div[^>]*class="[^"]*division[^"]*")|(?=<h\d[^>]*>\s*\d{1,2}U)', page)[1:]:
        name = re.search(r">\s*(\d{1,2}U[^<]{0,30})<", part)
        teams = []
        for row in re.findall(r"<tr[^>]*>.*?</tr>", part, re.S):
            c = cells(row)
            if len(c) >= 5 and c[1] and c[1] not in ("Open", "Team Name"):
                teams.append([c[1], c[2], c[-1] if re.match(r"^\d+-\d+", c[-1]) else "", c[3] if len(c) > 3 else ""])
        if name and teams:
            divisions.append({"name": name.group(1).strip(), "teams": teams})
    return divisions


def perfect_game_coming(ev):
    """The group page links one event per age; each has its own accepted-teams table."""
    group = curl(ev["url"])
    divisions = []
    for pid, label in re.findall(r"Default\.aspx\?event=(\d+)[^>]*>(.*?)</a>", group, re.S):
        age = re.search(r"\b(\d{1,2})U\b", re.sub(r"<[^>]+>", " ", label))
        page = curl(f"https://www.perfectgame.org/Events/TournamentTeams.aspx?event={pid}")
        i = page.find("Accepted Teams")
        teams = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page[i:] if i >= 0 else "", re.S):
            c = cells(row)
            if len(c) >= 3 and c[0] and c[0] != "Team":
                teams.append([c[0], c[2], "", c[1]])
        if teams:
            divisions.append({"name": f"{age.group(1)}U" if age else clean_label(label), "teams": teams})
    return divisions


def clean_label(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def eventconnect_coming(ev):
    """USA Softball / NSA: event info lists the classes; each class has its own team list."""
    m = re.match(r"(https://[^/]+)/pages/event/(?:detail/)?(\d+)", ev["url"])
    if not m:
        return None
    host, key = m.groups()
    try:
        info = json.loads(curl(f"{host}/api/v1/EP/info-v3.0/desktop/{key}"))
    except ValueError:
        return None
    if info.get("whosPlayingHidden"):
        return []
    divisions = []
    for d in info.get("divisions") or []:
        try:
            detail = json.loads(curl(f"{host}/api/v1/EP/division-detail-v3.0/{d['_key']}"))
        except ValueError:
            continue
        teams = []
        for t in detail.get("divisionTeams") or []:
            cls, _, name = (t.get("name") or "").strip().partition(" - ")
            if not name:
                cls, name = "", cls
            teams.append([name.strip(), t.get("location") or "", t.get("record") or "", cls.strip()])
        if teams:
            divisions.append({"name": d.get("name", "").strip(), "teams": teams})
    return divisions


def age_of(*texts):
    for t in texts:
        m = re.search(r"\b(\d{1,2})\s*(?:U\b|&\s*Under)", t or "", re.I)
        if m and 6 <= int(m.group(1)) <= 18:
            return f"{int(m.group(1))}U"
    return None


def main():
    data = json.loads((SITE / "data.json").read_text())
    reg = json.loads((ROOT / "registrations.json").read_text())
    horizon = (TODAY + dt.timedelta(days=LOOKAHEAD_DAYS)).isoformat()
    readers = {"USSSA": usssa_coming, "Grand Slam": grand_slam_coming, "Perfect Game": perfect_game_coming,
               "USA Softball": eventconnect_coming, "NSA": eventconnect_coming}
    todo = [e for e in data["events"] if e["sanction"] in readers and e["start"] <= horizon]
    prev = json.loads((SITE / "coming.json").read_text()) if (SITE / "coming.json").exists() else {}

    def work(ev):
        try:
            divs = readers[ev["sanction"]](ev)
        except Exception as exc:
            print(f"{ev['name']}: {exc}", file=sys.stderr)
            divs = None
        return ev["id"], divs

    coming = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        for eid, divs in pool.map(work, todo):
            if divs:
                coming[eid] = {"divisions": divs}
            elif eid in prev:  # keep the last good list if a fetch fails
                coming[eid] = prev[eid]
    (SITE / "coming.json").write_text(json.dumps(coming, separators=(",", ":")))

    by_id = {e["id"]: e for e in data["events"]}
    patterns = [p.lower() for p in reg.get("match", [])]
    found = []
    for eid, info in coming.items():
        for d in info["divisions"]:
            for name, *_ in d["teams"]:
                if any(p in name.lower() for p in patterns):
                    ev = by_id.get(eid)
                    if ev:
                        found.append({**ev, "eventId": eid, "team": age_of(name, d["name"]) or "",
                                      "teamName": name, "division": d["name"], "source": "auto"})
    cutoff = (TODAY - dt.timedelta(days=1)).isoformat()
    manual = [{**m, "source": "manual"} for m in reg.get("manual", []) if (m.get("end") or m["start"]) >= cutoff]
    regs = sorted(found + manual, key=lambda r: (r["start"], r.get("team", "")))
    prev_ours = json.loads((SITE / "ours.json").read_text()) if (SITE / "ours.json").exists() else {}
    prev_venues = {(r.get("eventId") or r["name"]): r.get("venues") for r in prev_ours.get("registrations", [])}
    for r in regs:  # ballparks with addresses, so families have everything in one place
        if not r.get("venues"):
            r["venues"] = (VENUES.get(r.get("eventId")) or (venues.for_event(r) if r.get("sanction") != "USSSA" else [])
                           or prev_venues.get(r.get("eventId") or r["name"]) or [])
    (SITE / "ours.json").write_text(json.dumps({"teams": reg.get("teams", []), "match": patterns, "registrations": regs}, indent=1))
    (SITE / "status.json").write_text(json.dumps({"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                                                  "requests": STATS, "teamLists": len(coming),
                                                  "venuesFound": sum(1 for v in VENUES.values() if v)}))
    teams_total = sum(len(d["teams"]) for v in coming.values() for d in v["divisions"])
    print(f"team lists for {len(coming)} events ({teams_total} teams); Shelby Steel: {len(found)} auto, {len(manual)} manual",
          file=sys.stderr)


if __name__ == "__main__":
    main()
