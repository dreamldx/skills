import json, re, time
from playwright.sync_api import sync_playwright

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'

ORIGIN = 'SFO'
WINDOWS = [
    ('2027-03-03', '2027-03-12'),
    ('2027-04-14', '2027-04-22'),
]
DESTINATIONS = ['TYO', 'TPE']
CABINS = ['eco', 'biz']

UID = {  # label -> name fragments as displayed
    'JL':  ['JAL', 'Japan Airlines'],
    'NH':  ['ANA', 'All Nippon'],
}

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/125.0 Safari/537.36')


def switch_cabin(page):
    eco = None
    for e in page.query_selector_all('text=/^Economy$/'):
        try:
            if e.is_visible():
                eco = e
                break
        except Exception:
            pass
    if not eco:
        print('CABIN_WARN: no visible Economy select', flush=True)
        return False
    eco.click(force=True, timeout=8000)
    page.wait_for_timeout(2500)
    biz = None
    for e in page.query_selector_all('text=/^Business$/'):
        try:
            if e.is_visible():
                biz = e
                break
        except Exception:
            pass
    if not biz:
        print('CABIN_WARN: no visible Business item', flush=True)
        return False
    biz.click(force=True, timeout=8000)
    page.wait_for_timeout(10000)
    return True


def fetch(page, dst, dep, ret, cabin):
    url = (f'https://www.google.com/travel/flights?hl=en&curr=USD'
           f'&q=flights%20from%20{ORIGIN}%20to%20{dst}%20on%20{dep}%20return%20{ret}')
    page.goto(url, wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(9000)
    if cabin == 'biz':
        switch_cabin(page)
        page.wait_for_timeout(3000)


def parse_li(page):
    rows = []
    for li in page.query_selector_all('li'):
        try:
            if not li.is_visible():
                continue
            t = (li.inner_text() or '').strip()
        except Exception:
            continue
        m = re.search(r'\$([\d,]+)', t)
        if not m or len(t) < 60:
            continue
        price = int(m.group(1).replace(',', ''))
        if not (200 <= price <= 30000):
            continue
        # route line like SFO-NRT / SFO-HND (arrows are unusual chars)
        route = ''
        for line in t.splitlines():
            mm = re.search(rf'\b({ORIGIN})\s*[^A-Za-z]{{1,3}}\s*([A-Z]{{3}})\b', line)
            if mm:
                route = f'{mm.group(1)}-{mm.group(2)}'
                break
        dur = ''
        md = re.search(r'(\d+)\s*hr(?:\s*(\d+)\s*min)?', t)
        if md:
            dur = md.group(0).replace('hr', 'h').replace('min', 'm').replace(' ', '')
        stops = 'nonstop' if re.search(r'Nonstop', t) else 'stops'
        # airline fragment: the line nearest above route line, or any line containing a target name
        airlines = []
        for lbl, frags in UID.items():
            for f in frags:
                if re.search(f, t):
                    airlines.append(lbl)
                    break
        rows.append({
            'price': price,
            'airlines': airlines,
            'route': route,
            'dur': dur,
            'stops': stops,
            'text': t[:240],
        })
    rows.sort(key=lambda r: r['price'])
    return rows


def main():
    results = {}
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EDGE, headless=True,
                              args=['--disable-blink-features=AutomationControlled'])
        ctx = b.new_context(user_agent=UA, locale='en-US',
                            viewport={'width': 1440, 'height': 900})
        page = ctx.new_page()
        page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        for dst in DESTINATIONS:
            for dep, ret in WINDOWS:
                for cabin in CABINS:
                    try:
                        fetch(page, dst, dep, ret, cabin)
                        body = page.inner_text('body')
                    except Exception as e:
                        print(f'ERR {dst} {dep} {cabin}: {e}', flush=True)
                        continue
                    if 'No results' in body and 'found' in body:
                        print(f'{dst} {dep}~{ret} {cabin}: NO_RESULTS', flush=True)
                        continue
                    rows = parse_li(page)
                    print(f'===== {dst} {dep} ~ {ret} [{cabin}] rows={len(rows)} =====', flush=True)
                    hits = []
                    for r in rows[:60]:
                        if not r['airlines']:
                            continue
                        hit = {'price': r['price'], 'airlines': r['airlines'],
                               'route': r['route'], 'dur': r['dur'], 'stops': r['stops']}
                        hits.append(hit)
                        print(f'{r["price"]} [{",".join(r["airlines"])}] {r["route"]} '
                              f'{r["dur"]} {r["stops"]} | {r["text"][:150]}', flush=True)
                    if not hits:
                        print('(0 target-airline hits)', flush=True)
                    results[f'{dst}|{dep}~{ret}|{cabin}'] = hits
        b.close()
    with open('sweep_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print('DONE', flush=True)


if __name__ == '__main__':
    main()