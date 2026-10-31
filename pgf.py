"""PGF (Premier Girls Fastpitch) on TournamentConnect.

The site's own pages call /callAPI.php with a base64 JSON body; it answers plain scripts once a session cookie
is set by loading the listing page. Used by fetch.py (listings) and teams.py (committed teams, ballparks).
"""
import base64, json, os, subprocess, tempfile

HOST = "https://softball.tournamentconnect.premiergirlsfastpitch.com"
LISTING = HOST + "/events/register/tournaments/provider/premiergirlsfastpitch"
PROVIDER = 76  # PGF national; state PGF groups (FL PGF, etc.) are listed under it
_JAR = os.path.join(tempfile.gettempdir(), "ssf-pgf.jar")
_UA = ["-A", "Mozilla/5.0 (Macintosh) ShelbySteelFinder"]
_ready = False


def call(controller, action, parameters):
    global _ready
    if not _ready:
        subprocess.run(["curl", "-s", "--max-time", "40", "-o", os.devnull, "-c", _JAR, "-b", _JAR, *_UA, LISTING])
        _ready = True
    body = base64.b64encode(json.dumps({"pass": 1, "controller": controller, "action": action, "parameters": parameters},
                                       separators=(",", ":")).encode()).decode()
    out = subprocess.run(["curl", "-s", "--max-time", "40", "-c", _JAR, "-b", _JAR, *_UA, "-H", "Referer: " + LISTING,
                          "-H", "Content-Type: application/json", "-H", "X-Requested-With: XMLHttpRequest",
                          "--data-binary", body, HOST + "/callAPI.php?e"], capture_output=True, text=True).stdout.strip()
    try:
        return json.loads(out)
    except ValueError:
        return json.loads(base64.b64decode(out))


def upcoming():
    return call("Event", "read", {"providerid": PROVIDER, "eventtypeid": 1, "eventids": None, "sportid": 4,
                                  "sort": "startdate", "limit": 300, "offset": 0, "entityid": None, "entity": "team",
                                  "historylabel": False, "futurelabel": True, "fltr": False, "filters": {"visible": 1}})


def event_url(eventid):
    return f"{LISTING}#event-{eventid}"


def venues(item):
    out = []
    for f in item.get("facilities") or []:
        addr = ", ".join(p for p in [f.get("physical_address"), f.get("physical_city"), f.get("physical_zip")] if p)
        out.append({"name": (f.get("name") or "").strip(), "address": addr, "ages": []})
    return out


def committed(item):
    """Committed teams by division, only when the director has made the list public on PGF's site."""
    ev = item["event"]
    if str(ev.get("commitmentsvisible")) != "1":
        return []
    rows = call("Event", "commitments", {"eventid": ev["eventid"], "providerid": ev["providerid"]})
    divisions = {}
    approval = str(ev.get("approved_status")) in ("1", "True")
    for t in rows if isinstance(rows, list) else []:
        name = f"{t.get('sportdivision') or ''} {t.get('sportskill') or ''}".strip()
        d = divisions.setdefault(name, {"name": name, "teams": [], "sort": (t.get("divisionsort") or 0, name)})
        status = "" if int(t.get("onWaitList") or 0) < 1 else (" · pending" if approval else " · waitlist")  # as PGF labels them
        cls = (t.get("sportskill") or "") + status
        d["teams"].append([(t.get("name") or "").strip(), "", "", cls])
    return [{"name": d["name"], "teams": d["teams"]} for d in sorted(divisions.values(), key=lambda d: d["sort"])]
