#!/usr/bin/env python3
"""
EventRadar Leipzig - Scraper
Quellen:
  1. QB Arena Website (QB Arena, Festwiese, Red Bull Arena Konzerte)
  2. OpenLigaDB API (RB Leipzig Heimspiele, kostenlos, kein Scraping)
"""

import re
import json
import urllib.request
from datetime import date, datetime

BASE_URL = "https://www.quarterback-immobilien-arena.de/events-tickets/events"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
}
TYPE_NAMES = ["Konzert","Sport","Show","Comedy","Musical","Kinder","Messe","Tanz","Ausstellung","Fest"]
VENUE_MAP = {
    "quarterback immobilien arena": "QB Arena",
    "red bull arena": "Red Bull Arena",
    "festwiese leipzig": "Festwiese Leipzig",
}

# ── QB Arena Scraper ──────────────────────────────────────────
def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")

def parse_qb(html):
    url_re = re.compile(r'href="(https://www\.quarterback-immobilien-arena\.de/events-tickets/eventdetail/event/[^"]+)"')
    detail_urls = {}
    for m in url_re.finditer(html):
        u = m.group(1)
        slug = u.split("/event/")[-1].split("/")[0]
        detail_urls[slug] = u

    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&nbsp;", " ", text)
    lines = [l.strip() for l in re.sub(r"\s+", "\n", text).split("\n") if l.strip()]

    date_re = re.compile(r"^(Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag),\s+(\d{2})\.(\d{2})\.(\d{4})$")
    time_re = re.compile(r"^(\d{1,2}:\d{2})$")
    ende_re = re.compile(r"ca\.\s*(\d{1,2}:\d{2})")

    events, i = [], 0
    while i < len(lines):
        dm = date_re.match(lines[i])
        if dm:
            day, month, year = dm.group(2), dm.group(3), dm.group(4)
            date_str = f"{year}-{month}-{day}"
            j = i + 1
            if j < len(lines) and date_re.match(lines[j]): j += 1
            title = lines[j] if j < len(lines) else ""
            j += 1

            einlass = beginn = ende = None
            venue, ev_type, cancelled = "QB Arena", "Event", False

            for k in range(j, min(j+25, len(lines))):
                l = lines[k]
                if date_re.match(l): break
                if l.lower() == "abgesagt": cancelled = True
                for key, val in VENUE_MAP.items():
                    if key in l.lower(): venue = val; break
                if l in TYPE_NAMES: ev_type = l
                tm = time_re.match(l)
                if tm:
                    if einlass is None: einlass = tm.group(1)
                    elif beginn is None: beginn = tm.group(1)
                em = ende_re.search(l)
                if em: ende = em.group(1)

            skip = {"Tickets","Details","Uhr","Einlass","Beginn","Ende","|",":","abgesagt"}
            if title and len(title) > 2 and not date_re.match(title) and title not in skip:
                ev_url = None
                title_slug = re.sub(r"[^a-z0-9]", "-", title.lower()).strip("-")
                for slug, url in detail_urls.items():
                    if slug in title_slug or title_slug[:10] in slug:
                        ev_url = url; break
                exists = any(e["date"]==date_str and e["title"]==title and e["venue"]==venue for e in events)
                if not exists:
                    events.append({"date":date_str,"title":title,"type":ev_type,"venue":venue,
                                   "einlass":einlass,"beginn":beginn,"ende":ende,
                                   "cancelled":cancelled,"url":ev_url})
        i += 1
    return events

def get_qb_events():
    all_events = []
    for page in range(1, 4):
        try:
            url = BASE_URL if page == 1 else f"{BASE_URL}?tx_ifabeventmanagement_events%5B%40widget_0%5D%5BcurrentPage%5D={page}"
            print(f"  QB Arena Seite {page}…")
            evs = parse_qb(fetch(url))
            print(f"  → {len(evs)} Events")
            all_events.extend(evs)
            if evs:
                last = max(e["date"] for e in evs)
                if (date.fromisoformat(last) - date.today()).days > 60:
                    break
        except Exception as ex:
            print(f"  ⚠ Seite {page}: {ex}")
            if page == 1: raise
    return all_events

# ── RB Leipzig via OpenLigaDB (offene API, kein Scraping) ─────
def get_rbl_heimspiele():
    """
    OpenLigaDB ist eine freie, offene API für Bundesliga-Daten.
    Keine Authentifizierung nötig, keine Scraping-Probleme.
    """
    events = []
    season = "2025"  # Saison 2025/26
    league = "bl1"   # Bundesliga

    url = f"https://api.openligadb.de/getmatchdata/{league}/{season}/34"  # Alle Spieltage
    # Besser: alle verbleibenden Spiele von Leipzig holen
    url = f"https://api.openligadb.de/getmatchdata/{league}/{season}"

    try:
        print("  RB Leipzig via OpenLigaDB…")
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "EventRadar/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            matches = json.loads(r.read().decode("utf-8"))

        print(f"  → {len(matches)} Spiele total in der API")

        # Filter: Nur RB Leipzig Heimspiele, noch nicht gespielt
        today_str = date.today().isoformat()
        for m in matches:
            team1 = m.get("team1", {}).get("teamName", "")
            team2 = m.get("team2", {}).get("teamName", "")
            is_finished = m.get("matchIsFinished", True)

            # RB Leipzig Heimspiel = team1 ist RBL
            if "Leipzig" not in team1: continue
            # Nur zukünftige oder heutige Spiele
            match_dt_str = m.get("matchDateTime", "")
            if not match_dt_str: continue

            # Parse datetime: "2026-04-11T15:30:00"
            try:
                dt = datetime.fromisoformat(match_dt_str.replace("Z",""))
            except:
                continue

            match_date = dt.date().isoformat()
            if match_date < today_str: continue

            beginn = dt.strftime("%H:%M")
            title = f"RB Leipzig - {team2}"

            events.append({
                "date": match_date,
                "title": title,
                "type": "Sport",
                "venue": "Red Bull Arena",
                "einlass": None,
                "beginn": beginn,
                "ende": None,
                "cancelled": False,
                "url": f"https://rbleipzig.com/de/spielplan/",
            })
            print(f"  + {match_date} {title} ({beginn})")

    except Exception as ex:
        print(f"  ⚠ OpenLigaDB Fehler: {ex}")

    return events

# ── HTML Update ───────────────────────────────────────────────
def val(x):
    if x is None: return "null"
    if isinstance(x, bool): return "true" if x else "false"
    return f'"{x}"'

def to_js(events):
    lines = [f'  {{date:{val(e["date"])},title:{val(e["title"])},type:{val(e["type"])},venue:{val(e["venue"])},einlass:{val(e["einlass"])},beginn:{val(e["beginn"])},ende:{val(e["ende"])},cancelled:{val(e["cancelled"])},url:{val(e["url"])}}}' for e in events]
    return "[\n" + ",\n".join(lines) + "\n]"

def update_html(events, today_str):
    html = open("index.html", encoding="utf-8").read()
    html = re.sub(r"const EMBEDDED_EVENTS = \[[\s\S]*?\];", f"const EMBEDDED_EVENTS = {to_js(events)};", html)
    html = re.sub(r'const EMBEDDED_DATE = "[^"]*";', f'const EMBEDDED_DATE = "{today_str}";', html)
    open("index.html", "w", encoding="utf-8").write(html)
    print(f"✅ {len(events)} Events in index.html geschrieben")

# ── Main ──────────────────────────────────────────────────────
def main():
    today_str = date.today().isoformat()
    print(f"🔍 EventRadar Scraper ({today_str})\n")

    print("📍 QB Arena Events:")
    qb_events = get_qb_events()

    print("\n⚽ RB Leipzig Heimspiele:")
    rbl_events = get_rbl_heimspiele()

    # Merge & deduplicate
    all_events = qb_events + rbl_events
    seen, unique = set(), []
    for e in all_events:
        k = f"{e['date']}|{e['title']}|{e['venue']}"
        if k not in seen:
            seen.add(k)
            unique.append(e)
    unique.sort(key=lambda e: e["date"])

    if len(unique) < 3:
        print(f"\n⚠ Nur {len(unique)} Events — index.html wird NICHT überschrieben")
        return

    print(f"\n📅 Gesamt: {len(unique)} Events")
    update_html(unique, today_str)

if __name__ == "__main__":
    main()
