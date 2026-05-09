#!/usr/bin/env python3
"""
EventRadar Leipzig - Scraper v2
Quellen:
  1. QB Arena / Festwiese: quarterback-immobilien-arena.de (mit Retry + Fallback-Header)
  2. RB Leipzig: football-data.org (kostenlose API, nur Token nötig)
  3. RB Leipzig Fallback: direkte Spielplan-Seite scrapen

Umgebungsvariablen (GitHub Actions Secrets):
  FOOTBALL_DATA_TOKEN  - kostenlos auf football-data.org registrieren
"""

import re
import json
import time
import urllib.request
import urllib.error
import os
from datetime import date, datetime, timedelta

# ── Konfiguration ─────────────────────────────────────────────
QB_URL = "https://www.quarterback-immobilien-arena.de/events-tickets/events"
FOOTBALL_DATA_TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN", "")
RBL_TEAM_ID = 721  # RB Leipzig ID bei football-data.org

TYPE_NAMES = ["Konzert","Sport","Show","Comedy","Musical","Kinder","Messe","Tanz","Ausstellung","Fest"]
VENUE_MAP = {
    "quarterback immobilien arena": "QB Arena",
    "quarterback": "QB Arena",
    "red bull arena": "Red Bull Arena",
    "festwiese": "Festwiese Leipzig",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

# ── HTTP Helper ───────────────────────────────────────────────
def fetch(url, headers=None, retries=3, delay=4):
    """Fetch URL mit Retry-Logik und wechselnden User-Agents."""
    base_headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if headers:
        base_headers.update(headers)

    for attempt in range(retries):
        base_headers["User-Agent"] = USER_AGENTS[attempt % len(USER_AGENTS)]
        try:
            req = urllib.request.Request(url, headers=base_headers)
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
                # Handle gzip
                if r.info().get("Content-Encoding") == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            print(f"  HTTP {e.code} bei {url} (Versuch {attempt+1}/{retries})")
            if e.code in (403, 429, 503) and attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
            elif e.code == 404:
                return None
            else:
                raise
        except Exception as e:
            print(f"  Fehler: {e} (Versuch {attempt+1}/{retries})")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise
    return None

def fetch_json(url, headers=None):
    base = {"Accept": "application/json", "User-Agent": USER_AGENTS[0]}
    if headers:
        base.update(headers)
    req = urllib.request.Request(url, headers=base)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))

# ── QB Arena Scraper ──────────────────────────────────────────
def parse_qb(html):
    """Parst QB Arena Events aus HTML."""
    # Detail-URLs sammeln
    url_re = re.compile(r'href="(https://www\.quarterback-immobilien-arena\.de/events-tickets/eventdetail/event/[^"]+)"')
    detail_urls = {}
    for m in url_re.finditer(html):
        u = m.group(1)
        slug = u.split("/event/")[-1].split("/")[0]
        detail_urls[slug] = u

    # HTML bereinigen
    text = re.sub(r"<script[\s\S]*?</script>", " ", html)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&#[0-9]+;", " ", text)
    lines = [l.strip() for l in re.sub(r"\s+", "\n", text).split("\n") if l.strip() and len(l.strip()) > 1]

    date_re = re.compile(r"^(Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag),\s+(\d{2})\.(\d{2})\.(\d{4})$")
    time_re = re.compile(r"^(\d{1,2}:\d{2})\s*(Uhr)?$")
    ende_re = re.compile(r"ca\.\s*(\d{1,2}:\d{2})")
    skip_words = {"Tickets","Details","Uhr","Einlass","Beginn","Ende","Mehr","Info",
                  "Jetzt","kaufen","buchen","ab","bis","von","ab","Veranstalter","|",":"}

    events, i = [], 0
    today_str = date.today().isoformat()

    while i < len(lines):
        dm = date_re.match(lines[i])
        if dm:
            day, month, year = dm.group(2), dm.group(3), dm.group(4)
            date_str = f"{year}-{month}-{day}"

            # Vergangenheit überspringen
            if date_str < today_str:
                i += 1
                continue

            # Nächste Zeile nach dem Datum = Titel (ggf. Datumswiederholung überspringen)
            j = i + 1
            while j < len(lines) and date_re.match(lines[j]):
                j += 1
            title = lines[j] if j < len(lines) else ""
            j += 1

            einlass = beginn = ende = None
            venue, ev_type, cancelled = "QB Arena", "Konzert", False

            for k in range(j, min(j + 30, len(lines))):
                l = lines[k]
                if date_re.match(l):
                    break
                if "abgesagt" in l.lower() or "cancelled" in l.lower():
                    cancelled = True
                for key, val in VENUE_MAP.items():
                    if key in l.lower():
                        venue = val
                        break
                if l in TYPE_NAMES:
                    ev_type = l
                tm = time_re.match(l)
                if tm:
                    t = tm.group(1)
                    if einlass is None:
                        einlass = t
                    elif beginn is None:
                        beginn = t
                em = ende_re.search(l)
                if em:
                    ende = em.group(1)

            # Titel validieren
            if (title and len(title) > 2
                    and not date_re.match(title)
                    and title not in skip_words
                    and not title.isdigit()
                    and len(title) < 120):
                ev_url = None
                title_slug = re.sub(r"[^a-z0-9]", "-", title.lower()).strip("-")
                for slug, url in detail_urls.items():
                    if slug[:8] in title_slug or title_slug[:8] in slug:
                        ev_url = url
                        break
                key = f"{date_str}|{title}|{venue}"
                if not any(f"{e['date']}|{e['title']}|{e['venue']}" == key for e in events):
                    events.append({
                        "date": date_str, "title": title, "type": ev_type, "venue": venue,
                        "einlass": einlass, "beginn": beginn, "ende": ende,
                        "cancelled": cancelled, "url": ev_url,
                    })
        i += 1
    return events

def get_qb_events():
    """Scrapt QB Arena Events (3 Seiten)."""
    all_events = []
    for page in range(1, 4):
        try:
            url = QB_URL if page == 1 else f"{QB_URL}?tx_ifabeventmanagement_events%5B%40widget_0%5D%5BcurrentPage%5D={page}"
            print(f"  QB Arena Seite {page}…")
            time.sleep(2)  # Höfliches Delay zwischen Requests
            html = fetch(url)
            if html is None:
                print(f"  → Seite {page} nicht erreichbar, übersprungen")
                continue
            evs = parse_qb(html)
            print(f"  → {len(evs)} Events")
            all_events.extend(evs)
            if evs:
                last = max(e["date"] for e in evs)
                if (date.fromisoformat(last) - date.today()).days > 60:
                    break
        except Exception as ex:
            print(f"  ⚠ Seite {page} Fehler: {ex}")
            if page == 1:
                print("  ⚠ QB Arena komplett nicht erreichbar")
    return all_events

# ── RB Leipzig via football-data.org ─────────────────────────
def get_rbl_football_data():
    """
    Nutzt football-data.org API (kostenlos, Token nötig).
    Registrierung: https://www.football-data.org/client/register
    Token als GitHub Secret FOOTBALL_DATA_TOKEN speichern.
    """
    if not FOOTBALL_DATA_TOKEN:
        print("  ⚠ Kein FOOTBALL_DATA_TOKEN gesetzt — football-data.org übersprungen")
        return []

    events = []
    today_str = date.today().isoformat()
    date_to = (date.today() + timedelta(days=90)).isoformat()

    url = f"https://api.football-data.org/v4/teams/{RBL_TEAM_ID}/matches?status=SCHEDULED&dateFrom={today_str}&dateTo={date_to}"
    try:
        print("  RB Leipzig via football-data.org…")
        data = fetch_json(url, headers={"X-Auth-Token": FOOTBALL_DATA_TOKEN})
        matches = data.get("matches", [])
        print(f"  → {len(matches)} Spiele")
        for m in matches:
            home = m.get("homeTeam", {}).get("name", "")
            away = m.get("awayTeam", {}).get("name", "")
            if "Leipzig" not in home:
                continue  # Nur Heimspiele
            utc_date = m.get("utcDate", "")
            if not utc_date:
                continue
            # UTC → CET/CEST (näherungsweise +1h/+2h, für Anzeige reicht +1h)
            dt_utc = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
            dt_local = dt_utc.replace(tzinfo=None) + timedelta(hours=1)
            match_date = dt_local.date().isoformat()
            beginn = dt_local.strftime("%H:%M")
            competition = m.get("competition", {}).get("name", "Bundesliga")
            title = f"RB Leipzig - {away}"
            if competition not in ("Bundesliga",):
                title += f" ({competition})"
            events.append({
                "date": match_date, "title": title, "type": "Sport", "venue": "Red Bull Arena",
                "einlass": None, "beginn": beginn, "ende": None,
                "cancelled": False, "url": "https://www.rbleipzig.com/de/tickets/",
            })
            print(f"  + {match_date} {title} ({beginn})")
    except Exception as e:
        print(f"  ⚠ football-data.org Fehler: {e}")
    return events

def get_rbl_openligadb():
    """
    OpenLigaDB Fallback — versucht es mit erweitertem Header-Set.
    """
    events = []
    today_str = date.today().isoformat()
    season = "2025"

    # Spieltage 28–34 abfragen (Saisonende)
    for spieltag in range(28, 35):
        url = f"https://api.openligadb.de/getmatchdata/bl1/{season}/{spieltag}"
        try:
            html = fetch(url, headers={"Accept": "application/json", "Referer": "https://www.openligadb.de/"})
            if not html:
                continue
            matches = json.loads(html)
            for m in matches:
                team1 = m.get("team1", {}).get("teamName", "")
                if "Leipzig" not in team1:
                    continue
                team2 = m.get("team2", {}).get("teamName", "")
                dt_str = m.get("matchDateTime", "")
                if not dt_str:
                    continue
                try:
                    dt = datetime.fromisoformat(dt_str.replace("Z", ""))
                except Exception:
                    continue
                match_date = dt.date().isoformat()
                if match_date < today_str:
                    continue
                beginn = dt.strftime("%H:%M")
                title = f"RB Leipzig - {team2}"
                events.append({
                    "date": match_date, "title": title, "type": "Sport", "venue": "Red Bull Arena",
                    "einlass": None, "beginn": beginn, "ende": None,
                    "cancelled": False, "url": "https://www.rbleipzig.com/de/spielplan/",
                })
                print(f"  + {match_date} {title} ({beginn})")
            time.sleep(1)
        except Exception as e:
            print(f"  OpenLigaDB Spieltag {spieltag}: {e}")
    return events

def get_rbl_events():
    """RBL Heimspiele — versucht football-data.org, dann OpenLigaDB."""
    print("⚽ RB Leipzig Heimspiele:")
    evs = get_rbl_football_data()
    if not evs:
        print("  Fallback: OpenLigaDB…")
        evs = get_rbl_openligadb()
    if not evs:
        print("  ⚠ Keine RBL-Daten verfügbar")
    return evs

# ── HTML Update ───────────────────────────────────────────────
def val(x):
    if x is None: return "null"
    if isinstance(x, bool): return "true" if x else "false"
    s = str(x).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'

def to_js(events):
    lines = []
    for e in events:
        line = (f'  {{date:{val(e["date"])},title:{val(e["title"])},type:{val(e["type"])},'
                f'venue:{val(e["venue"])},einlass:{val(e["einlass"])},beginn:{val(e["beginn"])},'
                f'ende:{val(e["ende"])},cancelled:{val(e["cancelled"])},url:{val(e["url"])}}}')
        lines.append(line)
    return "[\n" + ",\n".join(lines) + "\n]"

def update_html(events, today_str):
    with open("index.html", encoding="utf-8") as f:
        html = f.read()
    html = re.sub(r"const EMBEDDED_EVENTS = \[[\s\S]*?\];",
                  f"const EMBEDDED_EVENTS = {to_js(events)};", html)
    html = re.sub(r'const EMBEDDED_DATE = "[^"]*";',
                  f'const EMBEDDED_DATE = "{today_str}";', html)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ {len(events)} Events in index.html geschrieben")

# ── Main ──────────────────────────────────────────────────────
def main():
    today_str = date.today().isoformat()
    print(f"🔍 EventRadar Scraper v2 ({today_str})\n")

    # QB Arena
    print("📍 QB Arena Events:")
    qb_events = get_qb_events()

    # RB Leipzig
    rbl_events = get_rbl_events()

    # Merge & Deduplizierung
    all_events = qb_events + rbl_events
    seen, unique = set(), []
    for e in all_events:
        k = f"{e['date']}|{e['title']}|{e['venue']}"
        if k not in seen:
            seen.add(k)
            unique.append(e)
    unique.sort(key=lambda e: e["date"])

    print(f"\n📅 Gesamt: {len(unique)} Events")

    # Sicherheitsprüfung: Nur updaten wenn mindestens 1 Event gefunden
    # (statt 3 — QB Arena könnte wirklich leer sein)
    qb_count = sum(1 for e in unique if e["venue"] != "Red Bull Arena")
    rbl_count = sum(1 for e in unique if e["venue"] == "Red Bull Arena")
    print(f"   QB Arena/Festwiese: {qb_count}, Red Bull Arena: {rbl_count}")

    if len(unique) == 0:
        print("⚠ Null Events — index.html wird NICHT überschrieben (beide Quellen fehlgeschlagen)")
        exit(1)  # Exit code 1 → GitHub Actions zeigt Fehler an!

    update_html(unique, today_str)

if __name__ == "__main__":
    main()
