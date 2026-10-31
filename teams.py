#!/usr/bin/env python3
"""Pull registered-team lists ("Who's coming") and find Shelby Steel's registrations.

Reads site/data.json (from fetch.py) and registrations.json, writes:
  site/coming.json  {event id: {"divisions": [{"name", "teams": [[team, city, record]]}]}}
  site/ours.json    {"teams": [...], "registrations": [...]}  auto-detected + manual entries
Team lists come from USSSA and Grand Slam; other sanctions don't publish them openly.
"""
import datetime as dt, html, json, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
TODAY = dt.date.today()
LOOKAHEAD_DAYS = 150


def curl(url, data=None, jar=None):
    cmd = ["curl", "-sL", "--max-time", "40", "-A", "Mozilla/5.0 (Macintosh) ShelbySteelFinder"]
    if jar:
        cmd += ["-b", jar, "-c", jar]
    if data:
        cmd += ["--data", data]
    return subprocess.run(cmd + [url], capture_output=True, text=True).stdout


def cells(row):
    return [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]


def usssa_coming(ev):
    """Event page carries a nonce and the USSSA event id; the team list comes from admin-ajax."""
    jar = f"/tmp/ssf-{ev['id']}.jar"
    page = curl(ev["url"], jar=jar)
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
                current["teams"].append([c[1], c[2], record])
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
                teams.append([c[1], c[2], c[-1] if re.match(r"^\d+-\d+", c[-1]) else ""])
        if name and teams:
            divisions.append({"name": name.group(1).strip(), "teams": teams})
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
    todo = [e for e in data["events"] if e["sanction"] in ("USSSA", "Grand Slam") and e["start"] <= horizon]
    prev = json.loads((SITE / "coming.json").read_text()) if (SITE / "coming.json").exists() else {}

    def work(ev):
        try:
            divs = usssa_coming(ev) if ev["sanction"] == "USSSA" else grand_slam_coming(ev)
        except Exception as exc:
            print(f"{ev['name']}: {exc}", file=sys.stderr)
            divs = None
        return ev["id"], divs

    coming = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
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
            for name, city, _ in d["teams"]:
                if any(p in name.lower() for p in patterns):
                    ev = by_id.get(eid)
                    if ev:
                        found.append({**ev, "eventId": eid, "team": age_of(name, d["name"]) or "",
                                      "teamName": name, "division": d["name"], "source": "auto"})
    cutoff = (TODAY - dt.timedelta(days=1)).isoformat()
    manual = [{**m, "source": "manual"} for m in reg.get("manual", []) if (m.get("end") or m["start"]) >= cutoff]
    regs = sorted(found + manual, key=lambda r: (r["start"], r.get("team", "")))
    (SITE / "ours.json").write_text(json.dumps({"teams": reg.get("teams", []), "match": patterns, "registrations": regs}, indent=1))
    teams_total = sum(len(d["teams"]) for v in coming.values() for d in v["divisions"])
    print(f"team lists for {len(coming)} events ({teams_total} teams); Shelby Steel: {len(found)} auto, {len(manual)} manual",
          file=sys.stderr)


if __name__ == "__main__":
    main()
