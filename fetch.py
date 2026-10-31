#!/usr/bin/env python3
"""Pull travel-softball tournaments from each sanction and write site/data.json.

Sources fetched directly: USSSA, Perfect Game, Grand Slam, NSA, USA Softball (AL, FL).
Sources that block scripts (USFA on SincSports, PGF on TournamentConnect) are read
from cache/<source>.json, which the hourly Claude job refreshes through the browser.
Any source that fails keeps its last good data so the page never goes blank.
"""
import base64, datetime as dt, html, json, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
OUT = ROOT / "site" / "data.json"
STATES = ["AL", "GA", "FL", "TN", "MS"]
STATE_NAMES = {"ALABAMA": "AL", "GEORGIA": "GA", "FLORIDA": "FL", "TENNESSEE": "TN", "MISSISSIPPI": "MS"}
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
TODAY = dt.date.today()


def get(url):
    r = subprocess.run(["curl", "-sL", "--max-time", "40", "-A", "Mozilla/5.0 (Macintosh) ShelbySteelFinder", url],
                       capture_output=True, text=True)
    return r.stdout


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def infer_year(month, day):
    """Listings omit the year; pick the one that puts the date in the current season window."""
    year = TODAY.year
    d = dt.date(year, month, day)
    if d < TODAY - dt.timedelta(days=45):
        year += 1
    return year


def parse_dates(text):
    """'Nov 7-8', 'Jun 27 - Jul 2', 'Oct 31 - Nov 1', 'NOV 07' + end '07/18' -> (start, end) ISO."""
    t = text.upper().replace(",", " ")
    m = re.match(r"([A-Z]{3})\w*\s+(\d{1,2})(?:\s*-\s*(?:([A-Z]{3})\w*\s+)?(\d{1,2}))?(?:\s+(\d{4}))?", t.strip())
    if not m:
        return None, None
    mo1, d1, mo2, d2, yr = m.groups()
    mo1 = MONTHS[mo1]
    y1 = int(yr) if yr else infer_year(mo1, int(d1))
    start = dt.date(y1, mo1, int(d1))
    if d2:
        mo2n = MONTHS[mo2] if mo2 else mo1
        y2 = y1 + (1 if mo2n < mo1 else 0)
        end = dt.date(y2, mo2n, int(d2))
    else:
        end = start
    return start.isoformat(), end.isoformat()


def parse_ages(text):
    t = (text or "").upper().replace("HIGH SCHOOL", "HS")
    nums = [int(n) for n in re.findall(r"(\d{1,2})\s*U", t)]
    if "HS" in t or "18 & UNDER" in t:
        nums.append(18)
    nums += [int(n) for n in re.findall(r"(\d{1,2}) & UNDER", t)]
    if not nums:
        return None, None
    return min(nums), max(nums)


def state_of(loc, default=None):
    m = re.search(r",\s*([A-Z]{2})\b", (loc or "").upper())
    if m and m.group(1) in STATES:
        return m.group(1)
    for name, code in STATE_NAMES.items():
        if name in (loc or "").upper():
            return code
    return default


def tidy_city(loc):
    loc = re.sub(r"\s*,\s*([A-Za-z]{2})$", "", (loc or "").strip())
    loc = re.sub(r",\s*(FLORIDA|GEORGIA|ALABAMA|TENNESSEE|MISSISSIPPI)$", "", loc, flags=re.I)
    return loc.title() if loc.isupper() else loc


def event(sanction, name, start, end, state, city, ages, fee, url, teams=None):
    lo, hi = parse_ages(ages)
    return dict(sanction=sanction, name=clean(name), start=start, end=end, state=state, city=tidy_city(city),
                ages=clean(ages), ageMin=lo, ageMax=hi, fee=clean(fee), teams=teams, url=url)


# ---------- USSSA (each state has its own WordPress site) ----------
def usssa():
    out = []
    hosts = {"AL": "alfastpitch", "GA": "gafastpitch", "FL": "flfastpitch", "TN": "tnfastpitch", "MS": "msfastpitch"}
    for st, host in hosts.items():
        seen = set()
        for page in range(1, 40):
            h = get(f"https://{host}.usssa.com/events/?paged={page}")
            new = 0
            for blk in h.split('<div class="events-list-elem">')[1:]:
                blk = blk.split('<div class="event-block grid-item">')[0]
                m = re.search(r'events-list-elem-title">\s*<a href="([^"]+)"[^>]*>(.*?)</a>', blk, re.S)
                if not m:
                    continue
                def lis(cls):
                    s = re.search(r'class="%s">(.*?)</ul>' % cls, blk, re.S)
                    return [clean(x) for x in re.findall(r"<li[^>]*>(.*?)</li>", s.group(1), re.S)] if s else []
                info, lst = lis("events-list-elem-info"), lis("events-list-elem-list")
                key = (m.group(1), info[0] if info else "")
                if key in seen:
                    continue
                seen.add(key)
                new += 1
                start, end = parse_dates(info[0] if info else "")
                teams = next((int(x) for x in info[1:] if x.isdigit()), None)
                loc = lst[1] if len(lst) > 1 else ""
                out.append(event("USSSA", m.group(2), start, end, state_of(loc, st), loc,
                                 lst[0] if lst else "", next((x for x in info if "$" in x), ""), m.group(1), teams))
            if not new:
                break
    return out


# ---------- Perfect Game (filtered per state via base64 query params) ----------
def perfect_game():
    b = lambda s: base64.b64encode(s.encode()).decode()
    sp = b(TODAY.strftime("%m/%d/%Y") + " 12:00:00 AM")
    ep = b((TODAY + dt.timedelta(days=366)).strftime("%m/%d/%Y") + " 12:00:00 AM")
    out = []
    for st in STATES:
        url = (f"https://www.perfectgame.org/softball/schedule.aspx?ty=MjA=&fg=TkY=&dt=MA==&cl=MA==&dv=MA=="
               f"&st={b(st)}&sp={sp}&ep={ep}&tm=MA==")
        h = get(url)
        for grp in h.split('class="rgGroupHeader"')[1:]:
            m = re.search(r"href='\.\./Schedule/GroupedEvents\.aspx\?gid=(\d+)'[^>]*><span[^>]*>(.*?)</span>", grp, re.S)
            if not m:
                continue
            spans = re.findall(r"<span style='font-size:13px; display:block'>(.*?)</span>", grp)
            teams = re.search(r"TournamentTeamsGroup\.aspx\?gid=\d+'>(\d+)<", grp)
            loc = re.search(r"<div class='col-md-3'><div class='clearfix'></div><span style='display:inline-block'>(.*?)</span>", grp)
            s = re.search(r'hfStartDate" value="(\d+)/(\d+)/(\d{4})', grp)
            e = re.search(r'hfEndDate" value="(\d+)/(\d+)/(\d{4})', grp)
            if not s:
                continue
            start = dt.date(int(s.group(3)), int(s.group(1)), int(s.group(2))).isoformat()
            end = dt.date(int(e.group(3)), int(e.group(1)), int(e.group(2))).isoformat() if e else start
            city = clean(loc.group(1)) if loc else ""
            out.append(event("Perfect Game", m.group(2), start, end, state_of(city, st), city,
                             spans[0] if spans else "", "",
                             f"https://www.perfectgame.org/Schedule/GroupedEvents.aspx?gid={m.group(1)}",
                             int(teams.group(1)) if teams else None))
    return out


# ---------- Grand Slam Sports Tournaments ----------
def grand_slam():
    out = []
    for st in STATES:
        h = get(f"https://www.grandslamtournaments.com/fastpitch/Events?state={st}")
        for blk in re.split(r'<div class="media[^"]*" data-eventId="', h)[1:]:
            eid = blk.split('"')[0]
            name = re.search(r'<div class="h3 mt0 mb">\s*<strong>(.*?)</strong>', blk, re.S)
            date = re.search(r'<div class="h4 mb-sm">(.*?)</div>', blk, re.S)
            loc = re.search(r'<div class="h5">\s*<strong>(.*?)</strong>', blk, re.S)
            teams = re.search(r"(\d+) Teams Registered", blk)
            ages = " ".join(re.findall(r'data-agenumber="(\d+)"', blk))
            link = re.search(r'href="(/fastpitch/Events/Details/[^"]+)"', blk)
            if not (name and date):
                continue
            start, end = parse_dates(clean(date.group(1)))
            city = clean(loc.group(1)) if loc else ""
            age_txt = (f"{ages.split()[0]}U - {ages.split()[-1]}U" if ages else "")
            out.append(event("Grand Slam", name.group(1), start, end, state_of(city, st), city, age_txt, "",
                             "https://www.grandslamtournaments.com" + (link.group(1) if link else f"/fastpitch/Events?state={st}"),
                             int(teams.group(1)) if teams else None))
    return out


# ---------- EventConnect sites (NSA and the USA Softball state associations share this platform) ----------
def ec_ages(classes):
    """Class names look like '10O', '16/18O', '7/8uB/C', 'HS-O', '12U Gold'."""
    nums = []
    for c in classes:
        c = c.upper()
        nums += [int(n) for n in re.findall(r"\d{1,2}", c) if 6 <= int(n) <= 18]
        if "HS" in c:
            nums.append(18)
    if not nums:
        return ""
    lo, hi = min(nums), max(nums)
    label = lambda n: "18U/HS" if n == 18 else f"{n}U"
    return label(lo) if lo == hi else f"{label(lo)} - {label(hi)}"


def eventconnect(sanction, rows, link):
    out = []
    for e in rows:
        if e.get("sport") != "FP" or e.get("cancelled"):
            continue
        st = state_of(e.get("location", ""))
        if not st:
            continue
        teams = e.get("teamCnt")
        out.append(event(sanction, e["name"], e["starts"][:10], (e.get("ends") or e["starts"])[:10], st,
                         e.get("location", ""), ec_ages([c["name"] for c in e.get("competitionClassesList") or []]),
                         e.get("entryFee") or "", link(e), int(teams) if str(teams).isdigit() else None))
    return out


def nsa():
    rows = json.loads(get("https://nationalsoftballassociation.com/api/v1/Event/display/active"))
    return eventconnect("NSA", rows, lambda e: f"https://nationalsoftballassociation.com/event/{e['_key']}")


# AL and FL associations answer scripts directly; TN, MS and GA sit behind Cloudflare on registerplay.com,
# so the hourly job saves their feeds to cache/usa_softball_raw_<st>.json through the browser (see REFRESH.md).
USA_DIRECT = {"AL": "usasoftballofalabama.com", "FL": "usasoftballflorida.com"}
USA_BROWSER = {"TN": "tn.registerplay.com", "MS": "ms.registerplay.com", "GA": "ga.registerplay.com"}


def usa_softball():
    rows = []
    for host in USA_DIRECT.values():
        for e in json.loads(get(f"https://{host}/api/v1/Event/display/active")):
            e["host"] = host
            rows.append(e)
    for st in USA_BROWSER:
        p = CACHE / f"usa_softball_raw_{st.lower()}.json"
        if p.exists():
            rows += json.loads(p.read_text())
    return eventconnect("USA Softball", rows, lambda e: f"https://{e['host']}/pages/event/detail/{e['_key']}")


def from_cache(name):
    p = CACHE / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


SOURCES = {"usssa": ("USSSA", usssa), "perfect_game": ("Perfect Game", perfect_game),
           "grand_slam": ("Grand Slam", grand_slam), "nsa": ("NSA", nsa), "usa_softball": ("USA Softball", usa_softball), "usfa": ("USFA", None), "pgf": ("PGF", None)}


def main():
    CACHE.mkdir(exist_ok=True)
    OUT.parent.mkdir(exist_ok=True)
    prev = json.loads(OUT.read_text()) if OUT.exists() else {"sources": {}}
    now = dt.datetime.now().astimezone().isoformat(timespec="minutes")
    events, status = [], {}
    for key, (label, fn) in SOURCES.items():
        rows, ok = None, False
        if fn:
            try:
                rows = fn()
                ok = len(rows) > 0
            except Exception as e:  # keep last good data below
                print(f"{label}: {e}", file=sys.stderr)
            if ok:
                (CACHE / f"{key}.json").write_text(json.dumps({"updated": now, "events": rows}))
        cached = from_cache(key)
        if not ok and cached:
            rows = cached["events"]
        updated = now if ok else (cached or {}).get("updated") or prev["sources"].get(label, {}).get("updated")
        rows = [r for r in (rows or []) if r.get("state") in STATES and r.get("start")]
        events += rows
        status[label] = {"updated": updated, "count": len(rows), "fresh": ok or bool(fn is None and cached)}
        print(f"{label}: {len(rows)} events ({'fresh' if ok else 'cached'})", file=sys.stderr)
    cutoff = (TODAY - dt.timedelta(days=1)).isoformat()
    events = [e for e in events if (e.get("end") or e["start"]) >= cutoff]
    events.sort(key=lambda e: (e["start"], e["state"], e["name"]))
    if prev.get("events") == events:
        print("DATA_UNCHANGED: no new or changed tournaments; nothing to republish")
        return
    OUT.write_text(json.dumps({"updated": now, "sources": status, "events": events}, separators=(",", ":")))
    print(f"wrote {len(events)} events -> {OUT}", file=sys.stderr)
    print("DATA_CHANGED: republish data.json")


if __name__ == "__main__":
    main()
