#!/usr/bin/env python3
"""
EventRadar Leipzig - QB Arena Scraper
Runs via GitHub Actions every Monday, updates index.html with fresh events + links.
"""
 
import re
import urllib.request
from datetime import date
 
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
 
def fetch(page):
    url = BASE_URL if page == 1 else f"{BASE_URL}?tx_ifabeventmanagement_events%5B%40widget_0%5D%5BcurrentPage%5D={page}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")
 
def parse(html):
    # Extract event URLs from links like /events-tickets/eventdetail/event/xxx/123
    url_re = re.compile(r'href="(https://www\.quarterback-immobilien-arena\.de/events-tickets/eventdetail/event/[^"]+)"')
    detail_urls = {}  # slug -> full url
    for m in url_re.finditer(html):
        u = m.group(1)
        slug = u.split("/event/")[-1].split("/")[0]
        detail_urls[slug] = u
 
    # Strip HTML
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
                # Find matching URL by fuzzy matching title to slug
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
 
def to_js(events):
    def v(x):
        if x is None: return "null"
        if isinstance(x, bool): return "true" if x else "false"
        return f'"{x}"'
    lines = []
    for e in events:
        lines.append(f'  {{date:{v(e["date"])},title:{v(e["title"])},type:{v(e["type"])},venue:{v(e["venue"])},einlass:{v(e["einlass"])},beginn:{v(e["beginn"])},ende:{v(e["ende"])},cancelled:{v(e["cancelled"])},url:{v(e["url"])}}}')
    return "[\n" + ",\n".join(lines) + "\n]"
 
def update_html(events, today_str):
    html = open("index.html", encoding="utf-8").read()
    html = re.sub(r"const EMBEDDED_EVENTS = \[[\s\S]*?\];", f"const EMBEDDED_EVENTS = {to_js(events)};", html)
    html = re.sub(r'const EMBEDDED_DATE = "[^"]*";', f'const EMBEDDED_DATE = "{today_str}";', html)
    open("index.html","w",encoding="utf-8").write(html)
    print(f"✅ {len(events)} events written (Stand: {today_str})")
 
def main():
    today_str = date.today().isoformat()
    print(f"🔍 Scraping QB Arena ({today_str})")
    all_events = []
    for page in range(1, 4):
        try:
            print(f"  Page {page}…")
            evs = parse(fetch(page))
            print(f"  → {len(evs)} events")
            all_events.extend(evs)
            if evs:
                last = max(e["date"] for e in evs)
                if (date.fromisoformat(last) - date.today()).days > 60:
                    break
        except Exception as ex:
            print(f"  ⚠ Page {page}: {ex}")
            if page == 1: raise
 
    seen, unique = set(), []
    for e in all_events:
        k = f"{e['date']}|{e['title']}|{e['venue']}"
        if k not in seen: seen.add(k); unique.append(e)
    unique.sort(key=lambda e: e["date"])
 
    if len(unique) < 3:
        print(f"⚠ Nur {len(unique)} Events gefunden - zu wenig, index.html wird NICHT überschrieben")
        print("  Die QB Arena Website hat den Scraper möglicherweise blockiert.")
        return
 
    print(f"📅 {len(unique)} Events gefunden")
    update_html(unique, today_str)
 
if __name__ == "__main__":
    main()
 
