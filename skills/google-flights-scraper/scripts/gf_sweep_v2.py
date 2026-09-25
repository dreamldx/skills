"""Generic Google Flights morning-flight sweeper.

Usage:
  python gf_sweep_v2.py --origin SFO --dest SEA --cutoff 12:00 \
      --dates 2027-03-03 2027-03-05 2027-03-07 --out out.json
  python gf_sweep_v2.py --dates 2027-03-03 2027-03-07 --return 2027-03-10 \
      --cutoff 10:00        # round-trip morning flights
  python gf_sweep_v2.py --dates 2027-03-03 --sweep-days 3 \
      --cutoff 11:00        # batch scan 3 consecutive days (max 3)
  python gf_sweep_v2.py --dates 2027-03-03 --cabin biz   # business cabin
"""
import argparse, json, re, sys
from playwright.sync_api import sync_playwright

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/125.0 Safari/537.36')

# name fragment (in card text) -> IATA; longest first for findall ordering
AIRLINES = [
    ('Air Canada', 'AC'), ('British Airways', 'BA'), ('Japan Airlines', 'JL'),
    ('Hawaiian', 'HA'), ('Sun Country', 'SY'), ('Allegiant', 'G4'),
    ('Southwest', 'WN'), ('American', 'AA'), ('Alaska', 'AS'),
    ('JetBlue', 'B6'), ('United', 'UA'), ('Delta', 'DL'),
    ('Spirit', 'NK'), ('Frontier', 'F9'), ('Avelo', 'XP'),
    ('Lufthansa', 'LH'), ('Emirates', 'EK'), ('Qatar', 'QR'),
]


def to_minutes(dep):
    """'6:45 AM' -> 405; '13:05' or '1:05 PM' -> 785. Bare '12:00' -> noon."""
    if not dep:
        return None
    ap = None
    if ' ' in dep:
        t, ap = dep.rsplit(' ', 1)
    else:
        t = dep
    hh, mm = t.split(':')
    h = int(hh) % 12
    if ap == 'PM':
        h += 12
    elif ap is None and int(hh) >= 12:
        h = int(hh)  # bare 24h-form time
    return h * 60 + int(mm)


def click_visible(page, selector, wait_ms):
    for e in page.query_selector_all(selector):
        try:
            if e.is_visible():
                e.click(force=True, timeout=8000)
                page.wait_for_timeout(wait_ms)
                return True
        except Exception:
            pass
    return False


def switch_cabin(page):
    if not click_visible(page, 'text=/^Economy$/', 2500):
        print('CABIN_WARN: no visible Economy select', flush=True)
        return False
    if not click_visible(page, 'text=/^Business$/', 10000):
        print('CABIN_WARN: no visible Business item', flush=True)
        return False
    return True


def parse_li(page, origin, max_price=5000):
    seen, rows = set(), []
    for li in page.query_selector_all('li'):
        try:
            if not li.is_visible():
                continue
            t = (li.inner_text() or '').strip()
        except Exception:
            continue
        if len(t) < 60:
            continue
        m = re.search(r'\$([\d,]+)', t)
        if not m:
            continue
        price = int(m.group(1).replace(',', ''))
        if not (40 <= price <= max_price):
            continue
        route = ''
        for line in t.splitlines():
            mm = re.search(rf'\b({origin})\s*[^A-Za-z]{{1,3}}\s*([A-Z]{{3}})\b', line)
            if mm:
                route = f'{mm.group(1)}-{mm.group(2)}'
                break
        dur = ''
        md = re.search(r'(\d+)\s*hr(?:\s*(\d+)\s*min)?', t)
        if md:
            dur = f"{md.group(1)}h" + (f"{md.group(2)}m" if md.group(2) else '')
        stops = 'nonstop' if re.search(r'Nonstop', t) else 'stops'
        layover = ''
        mst = re.search(r'(\d+)\s*hr(?:\s*(\d+)\s*min)?\s*([A-Z]{3})\s*$', t, re.M)
        if mst and stops == 'stops':
            layover = mst.group(3)
        dep = ''
        mt = re.search(r'(\d{1,2}:\d{2})\s*(AM|PM)', t)
        if mt:
            dep = f'{mt.group(1)} {mt.group(2)}'
        carriers = []
        head = t[:220]
        for frag, code in AIRLINES:
            if re.search(re.escape(frag), head) and code not in carriers:
                carriers.append(code)
        key = (price, dep, route, dur)
        if key in seen:
            continue
        seen.add(key)
        rows.append({'price': price, 'carriers': carriers, 'route': route,
                     'dur': dur, 'stops': stops, 'layover': layover,
                     'dep': dep})
    rows.sort(key=lambda r: r['price'])
    return rows


def fetch(page, origin, dest, dep_date, ret_date=None, cabin='eco'):
    trip_word = f'return {ret_date}' if ret_date else 'one way'
    url = (f'https://www.google.com/travel/flights?hl=en&curr=USD'
           f'&q=flights%20from%20{origin}%20to%20{dest}%20on%20{dep_date}%20{trip_word}')
    page.goto(url, wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(9000)
    if cabin == 'biz':
        switch_cabin(page)
    body = page.inner_text('body')
    trip = 'round' if re.search(r'Round trip', body) else (
        'one-way' if re.search(r'One-way', body) else '?')
    m = re.search(r'returning\s+(\d{4}-\d{2}-\d{2})', body)
    ret = m.group(1) if m else None
    if ret_date and (trip != 'round' or ret != ret_date):
        print(f'TRIP_WARN: expected round trip returning {ret_date}, '
              f'page shows {trip} returning {ret}', flush=True)
    if not ret_date and trip == 'round':
        print(f'TRIP_WARN: asked one-way, page shows round trip returning {ret}', flush=True)
    return trip, ret, body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--origin', default='SFO')
    ap.add_argument('--dest', default='SEA')
    ap.add_argument('--cutoff', default='12:00', help='latest morning departure, e.g. 12:00')
    ap.add_argument('--dates', nargs='+', required=True,
                    help='one or more departure dates (YYYY-MM-DD)')
    ap.add_argument('--return', dest='ret', default=None,
                    help='return date for round-trip mode, e.g. 2027-03-10')
    ap.add_argument('--cabin', choices=['eco', 'biz'], default='eco',
                    help='cabin class: eco (default) or biz')
    ap.add_argument('--sweep-days', type=int, default=0,
                    help='batch scan: scan N consecutive days from the first date (max 3)')
    ap.add_argument('--out', default='gf_morning_results.json')
    args = ap.parse_args()

    dates = args.dates
    if args.sweep_days:
        if not (1 <= args.sweep_days <= 3):
            print('SWEEP_ERR: --sweep-days must be 1..3', flush=True)
            sys.exit(2)
        base = dates[0]
        from datetime import date, timedelta
        d0 = date.fromisoformat(base)
        dates = [(d0 + timedelta(days=i)).isoformat() for i in range(args.sweep_days)]
        print(f'SWEEP: scanning {args.sweep_days} days: {dates[0]} .. {dates[-1]}', flush=True)

    cutoff = to_minutes(args.cutoff) or 720

    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EDGE, headless=True,
                              args=['--disable-blink-features=AutomationControlled'])
        ctx = b.new_context(user_agent=UA, locale='en-US',
                            viewport={'width': 1440, 'height': 900})
        page = ctx.new_page()
        page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        for d in dates:
            try:
                trip, ret, body = fetch(page, args.origin, args.dest, d, args.ret, args.cabin)
            except Exception as e:
                print(f'ERR {d}: {e}', flush=True)
                continue
            if 'No results' in body and 'found' in body:
                print(f'{d}: NO_RESULTS', flush=True)
                out[d] = {'trip': trip, 'return': ret, 'cabin': args.cabin, 'morning': []}
                continue
            rows = parse_li(page, args.origin, 30000 if args.cabin == 'biz' else 5000)
            morning = sorted(
                [r for r in rows if (to_minutes(r['dep']) or 1 << 30) <= cutoff],
                key=lambda r: (r['price'], to_minutes(r['dep'])))
            trip_label = f'round(return {ret})' if ret else trip
            print(f'===== {d} [{trip_label}][{args.cabin}] rows={len(rows)} morning<={args.cutoff}={len(morning)} =====', flush=True)
            for r in morning[:8]:
                lay = f" via {r['layover']}" if r['layover'] else ''
                print(f"${r['price']} {','.join(r['carriers'])} {r['dep']} "
                      f"{r['route']} {r['dur']} {r['stops']}{lay}", flush=True)
            out[d] = {'trip': trip, 'return': ret, 'cabin': args.cabin, 'morning': morning}
        b.close()
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('DONE', flush=True)


if __name__ == '__main__':
    main()