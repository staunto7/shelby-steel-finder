"""Ballparks for an event: [{"name", "address"}], read from the sanction's event pages."""
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


def usssa(page):
    m = re.search(r"data-map-locations='([^']+)'", page)
    if not m:
        return []
    try:
        spots = json.loads(html.unescape(m.group(1)))
    except ValueError:
        return []
    clean_addr = lambda a: ", ".join(p for p in (x.strip() for x in _text(a).split(",")) if p and p != "None")
    return [{"name": _text(s["infoWindow"]["title"]), "address": clean_addr(s["infoWindow"]["address"])}
            for s in spots if s.get("infoWindow", {}).get("title")]


def grand_slam(url):
    page = _get(url.replace("/Events/Details/", "/Events/Locations/"))
    return [{"name": _text(t), "address": _text(f"{a}, {b}")}
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
