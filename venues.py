"""Ballparks for an event: [{"name", "address", "ages"}], read from the sanction's event pages.

"ages" lists the age groups that play there when the sanction says so (USA Softball/NSA, Perfect Game, USFA);
an empty list means the sanction doesn't break it down.
"""
import html, json, re, subprocess, time


def _get(url):
    for wait in (0, 8, 25):  # back off if the site says too many requests
        time.sleep(wait)
        out = subprocess.run(["curl", "-sL", "--max-time", "40", "-A", "Mozilla/5.0 (Macintosh) ShelbySteelFinder",
                              "-w", "\n%{http_code}", url], capture_output=True, text=True).stdout
        body, _, code = out.rpartition("\n")
        if code != "429":
            return body
    return ""


def _text(s):
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


def age_num(name):
    """Age group from a division name: "12U Open" -> 12, "14 & Under" -> 14, "HSO"/"High School" -> 18, "12C" -> 12."""
    head = re.split(r"\s+-\s+", name or "")[0]
    if re.search(r"high school|\bHS", head, re.I):
        return 18
    nums = [int(n) for n in re.findall(r"\d{1,2}", head) if 6 <= int(n) <= 18]
    return max(nums) if nums else None


def merge(spots):
    """Combine the same ballpark listed more than once (e.g. once per age group), joining its ages."""
    out = {}
    for v in spots:
        if not v.get("name"):
            continue
        k = v["name"].lower()
        cur = out.setdefault(k, {"name": v["name"], "address": v.get("address", ""), "ages": []})
        cur["address"] = cur["address"] or v.get("address", "")
        cur["ages"] = sorted(set(cur["ages"]) | set(v.get("ages") or []))
    return list(out.values())


def perfect_game(event_id, age):
    """Each Perfect Game age group is its own event with its own ballparks page."""
    page = _get(f"https://www.perfectgame.org/Events/Locations.aspx?event={event_id}")
    names = dict(re.findall(r'lblBallParkNames_(\d+)"[^>]*>([^<]*)<', page))
    addrs = dict(re.findall(r'lblBallParkAddresses_(\d+)"[^>]*>([^<]*)<', page))
    return [{"name": _text(n), "address": _text(addrs.get(i)), "ages": [age] if age else []} for i, n in names.items()]


def eventconnect(info):
    """USA Softball / NSA event info lists facilities with the divisions assigned to each."""
    out = []
    for f in info.get("facilities") or []:
        ages = sorted({a for d in f.get("divisions") or [] if (a := age_num(d.get("name")))})
        addr = ", ".join(p for p in [f.get("address"), f.get("location"), f.get("zip")] if p)
        out.append({"name": _text(f.get("name")), "address": addr, "ages": ages})
    return out


def usssa(page):
    m = re.search(r"data-map-locations='([^']+)'", page)
    if not m:
        return []
    try:
        spots = json.loads(html.unescape(m.group(1)))
    except ValueError:
        return []
    clean_addr = lambda a: ", ".join(p for p in (x.strip() for x in _text(a).split(",")) if p and p != "None")
    return [{"name": _text(s["infoWindow"]["title"]), "address": clean_addr(s["infoWindow"]["address"]), "ages": []}
            for s in spots if s.get("infoWindow", {}).get("title")]


def grand_slam(url):
    page = _get(url.replace("/Events/Details/", "/Events/Locations/"))
    return [{"name": _text(t), "address": _text(f"{a}, {b}"), "ages": []}
            for t, a, b in re.findall(r'data-title="([^"]*)" data-line1="([^"]*)" data-line2="([^"]*)"', page)]


def for_event(ev, page=None):
    try:
        if ev.get("sanction") == "USSSA" and ev.get("url"):
            return usssa(page if page is not None else _get(ev["url"]))
        if ev.get("sanction") == "Grand Slam" and ev.get("url"):
            return grand_slam(ev["url"])
    except Exception:
        pass
    return []
