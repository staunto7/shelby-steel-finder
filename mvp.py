"""MVP Sports fastpitch (mvpsports.net): listings, "Teams Currently Registered", ballparks, and pool play / brackets.

Each tournament page lists its complex and address, the registered teams by division, and, once posted,
per-age links to iTournamentBrackets pool schedules and elimination brackets.
Used by fetch.py (listings), teams.py (teams, ballparks) and games.py (pools, brackets).
"""
import html, re, subprocess

LISTING = "https://www.mvpsports.net/our-tournaments/"
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}


def get(url):
    return subprocess.run(["curl", "-sL", "--max-time", "40", "-A", "Mozilla/5.0 (Macintosh) ShelbySteelFinder", url],
                          capture_output=True, text=True).stdout


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def dates(s):
    """'Sat November 7th 2026' or 'Sat November 7th - Sun November 8th 2026' -> ('2026-11-07', '2026-11-08')."""
    year = re.search(r"(20\d\d)", s)
    days = [(MONTHS[m.lower()], int(d)) for m, d in re.findall(r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?", s)
            if m.lower() in MONTHS]
    if not (year and days):
        return None, None
    iso = [f"{year.group(1)}-{m:02d}-{d:02d}" for m, d in days]
    return iso[0], iso[-1]


def listing():
    """Rows of (date text, url, name, fee text) from the Our Tournaments table."""
    page = get(LISTING)
    out = []
    for when, url, name, fee in re.findall(r'<tr><td>(.*?)</td><td><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?</td><td>(.*?)</td>', page, re.S):
        name = text(name).split("*")[0].strip()  # names carry ***marketing*** after the title
        if name:
            out.append((text(when), url.replace("http://", "https://"), name, text(fee)))
    return out


def detail(page):
    """Complex name and address from a tournament page's details table."""
    field = lambda k: text((re.search(rf"<td>{k}:</td><td>(.*?)</td>", page, re.S) or [None, ""])[1])
    return {"complex": field("Complex"), "address": field("Location"), "dates": field(r"Date\(s\)")}


STREET = r"(?:DRIVE|DR|ROAD|RD|STREET|ST|AVENUE|AVE|HIGHWAY|HWY|BLVD|BOULEVARD|LANE|LN|PARKWAY|PKWY|WAY|CIRCLE|CIR|COURT|CT|TRAIL|TRL|PLACE|PL)\.?"


def city(address):
    """'130 SPORTSPLEX DRIVE VALLEY, AL 36854' -> 'Valley' (the address has no comma between street and city)."""
    before = (address or "").split(",")[0].upper()
    parts = re.split(rf"\b{STREET}\b", before)
    town = parts[-1].strip() if len(parts) > 1 else (before.split() or [""])[-1]
    town = re.sub(r"^(?:EAST|WEST|NORTH|SOUTH|E|W|N|S)\s+(?=\S)", "", town)  # "Glade Road East Anniston"
    return town.title()


def teams(page):
    i = page.find("Teams Currently Registered")
    if i < 0:
        return []
    block = page[i:page.find("</table>", i)]
    out = []
    for div, names in re.findall(r"<td valign=top>(.*?)</td><td[^>]*>(.*?)</td>", block, re.S):
        rows = [[text(n), "", "", ""] for n in names.split("<br>") if text(n)]
        if rows:
            out.append({"name": text(div), "teams": rows})
    return out


def venues(page):
    d = detail(page)
    addr = re.sub(r",\s*([A-Za-z]{2})\b", lambda m: ", " + m.group(1).upper(), d["address"].title())
    return [{"name": d["complex"].title(), "address": addr, "ages": []}] if d["complex"] else []


def links(page):
    """[(division label, pool schedule url, bracket url)] for divisions that have posted them."""
    i = page.find("Tournament Links")
    out = []
    for row in re.findall(r"<tr>(.*?)</tr>", page[i:] if i >= 0 else "", re.S):
        label = re.search(r"<b>(.*?)</b>", row)
        pool = re.search(r'href="([^"]*LMPoolPlayGames[^"]*)"', row)
        bracket = re.search(r'href="([^"]*LMTournamentBrackets[^"]*)"', row)
        if label and (pool or bracket):
            out.append((text(label.group(1)), pool and html.unescape(pool.group(1)), bracket and html.unescape(bracket.group(1))))
    return out


def game_time(day, clock, year):
    """'Sat, Oct 31' + '9:00 AM' -> '2026-10-31T09:00' (local time at the park, as posted)."""
    m = re.search(r"([A-Za-z]{3})[a-z]*\s+(\d{1,2})", day)
    t = re.search(r"(\d{1,2}):(\d\d)\s*([AP]M)", clock or "", re.I)
    mon = next((i for k, i in MONTHS.items() if m and k.startswith(m.group(1).lower())), None)
    if not (mon and t):
        return f"{day} {clock}".strip()
    h = int(t.group(1)) % 12 + (12 if t.group(3).upper() == "PM" else 0)
    return f"{year}-{mon:02d}-{int(m.group(2)):02d}T{h:02d}:{t.group(2)}"


def pool_games(url, year):
    """Games from an iTournamentBrackets pool schedule (Game, score, Team One, score, Team Two, Location, Date, Time)
    and its Standings table (Team, W, L, T, PCT, A, AA, F, AF, DIFF), best first as the site lists them."""
    page = get(url)
    standings = []
    j = page.find('id="lblPoolPlayStandings"')
    for row in re.findall(r'<tr class="lmTableCell[^"]*"\s*>(.*?)</tr>', page[j:page.find("</table>", j)] if j >= 0 else "", re.S):
        c = [text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(c) >= 10 and c[0]:
            n = lambda v: int(v) if re.fullmatch(r"-?\d+", v) else None
            standings.append({"team": c[0], "w": n(c[1]) or 0, "l": n(c[2]) or 0, "t": n(c[3]) or 0,
                              "ra": n(c[5]), "rs": n(c[7]), "rd": n(c[9])})
    i = page.find('id="lblPoolPlay"')
    games = []
    for row in re.findall(r'<tr class="lmTableCell[^"]*"\s*>(.*?)</tr>', page[i:] if i >= 0 else "", re.S):
        c = [text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(c) >= 8 and c[2] and c[4]:
            games.append({"time": game_time(c[6], c[7], year), "field": c[5], "game": c[0], "a": c[2], "b": c[4],
                          "as": c[1] or None, "bs": c[3] or None, "aClass": "", "bClass": ""})
    return games, standings


def bracket(url):
    """Bracket page body for a sandboxed frame; styles load from iTournamentBrackets via <base>."""
    page = get(url)
    styles = "".join(re.findall(r'<link[^>]+stylesheet[^>]*>', page, re.I))
    body = re.search(r"<body[^>]*>(.*)</body>", page, re.S | re.I)
    body = body.group(1) if body else ""
    start = body.find('<span id="lblBracketName"')  # skip the site's banner and ad block above the bracket
    body = body[start:] if start >= 0 else body
    body = re.sub(r"<script.*?</script>|<select.*?</select>|<input[^>]*>|<ins[^>]*>.*?</ins>", "", body, flags=re.S | re.I)
    return '<base href="https://www.itournamentbrackets.com/">' + styles, body
