---
name: google-flights-scraper
description: Scrape flight data (prices, airlines, routes, durations, stops) from Google Flights. Use this whenever the user wants to fetch, scrape, query, or collect live flight prices/options from Google Flights, sweep multiple routes/date-windows/cabins, or extract fare data for any origin to one or more destinations across a range of dates. Triggers on phrases like "get flight prices", "scrape Google Flights", "compare fares", "sweep routes", "cheapest flight to X", even if the user doesn't explicitly say "scrape".
---

# Google Flights Scraper

Fetch live flight results from Google Flights using Playwright (Chromium/Edge) and parse them into structured JSON. Drive the real Google Flights UI headlessly, read the rendered `li` result cards, and filter to target airlines.

## When to use
- User wants current flight prices/options for specific routes, dates, or cabins.
- User wants to sweep many date windows / destinations / cabins and save all results.
- User wants a structured dataset (price, airline, route, duration, stops) rather than screenshots.

## Prerequisites / compatibility
- Python 3.9+ with `playwright` installed (`pip install playwright`).
- A Chromium-family browser. Example: Microsoft Edge at `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`. Adjust `EDGE` if needed.
- Network access to `google.com/travel/flights`.

## Core approach
Google Flights loads results client-side. The reliable method is:
1. Launch headless Chromium/Edge with a real desktop UA and `--disable-blink-features=AutomationControlled`.
2. Hide the `navigator.webdriver` flag via `add_init_script` to look like a normal browser.
3. Navigate to a deep-link URL that encodes the query (origin, destination, dates, currency).
4. Wait for the results to render.
5. Verify the trip type on the page (see "Trip type" above) - confirm one-way vs round trip and the exact return date if any.
6. Read the `li` result cards from the page.
7. Parse each card's text for price, route, duration, stops, and airline names.

### The deep-link URL format
Use the `q` query parameter to encode the search. This avoids fighting the on-page form:
```
https://www.google.com/travel/flights?hl=en&curr=USD&q=flights from SFO to TYO on 2027-03-03 return 2027-03-12
```
- `hl=en` -> English UI (keeps parsing stable).
- `curr=USD` -> prices in USD.
- `q=flights from <ORIGIN> to <DEST> on <YYYY-MM-DD> return <YYYY-MM-DD>`.

### Trip type: ALWAYS say it explicitly (one-way vs round trip)
The single most expensive gotcha. If the `q` string has `on <date>` but NO `return`, Google Flights does **not** treat it as one-way. It silently defaults to a round trip and auto-selects a return date (observed: departure + 4 days). You will scrape round-trip prices while believing they are one-way fares - the numbers are roughly double, and any comparison/summary you report is wrong.

- For one-way fares, write the trip type explicitly: `q=flights from SFO to SEA on 2027-03-03 one way` (`one-way` also works).
- For round trips, always include the exact return date: `q=... on 2027-03-03 return 2027-03-07`. Never rely on the implicit default return date; it varies and changes the price. In scripts, prefer an explicit `--return <date>` flag that both builds the URL and validates the rendered page (see `gf_sweep_v2.py`).
- ALWAYS verify the trip type after results render, before parsing/reporting: scan the body text for `One-way` vs `Round trip`, and for the `returning YYYY-MM-DD` string (e.g. "Track prices from SFO to SEA departing 2027-03-03 and returning 2027-03-07"). If you asked for one-way but the page says `Round trip` with a `returning ...` date, the prices are round-trip fares - fix the URL and re-fetch. Never report a price without knowing which it is.

### Switching cabin (economy -> business)
Google Flights defaults to Economy. To get Business results, click the visible "Economy" select, then click the visible "Business" item, and wait for the page to reload results:
1. Find a visible `text=/^Economy$/` element and click it.
2. Wait ~2.5s.
3. Find a visible `text=/^Business$/` element and click it.
4. Wait ~10s for results to refresh.

### Parsing result cards
For each visible `li` on the page:
- Extract price with `re.search(r'\$([\d,]+)', text)` - the first `$` amount is the fare.
- Sanity-check the price is within a plausible range (e.g. 200-30000 USD) to skip junk.
- Extract the route by finding a line matching `ORIGIN <sep> DEST` (e.g. `SFO-NRT`). The separator between airport codes is often an unusual arrow character, so match `[^A-Za-z]{1,3}` between codes.
- Extract duration from `(\d+)\s*hr(?:\s*(\d+)\s*min)?`.
- Mark `nonstop` if the text contains "Nonstop", else `stops`.
- Detect target airlines by matching known name fragments (e.g. "JAL"/"Japan Airlines" -> `JL`, "ANA"/"All Nippon" -> `NH`).
- Sort results ascending by price.

## Output format
Save results as JSON keyed by a query descriptor, e.g.:
```json
{
  "TYO|2027-03-03~2027-03-12|eco": [
    {"price": 887, "airlines": ["JL"], "route": "SFO-NRT", "dur": "11h45m", "stops": "nonstop"}
  ]
}
```

## Workflow
1. Define the search space: list of destinations, date windows, and cabins.
2. For each combination, build the deep-link URL, fetch, wait, parse, and collect hits.
3. Filter to target airlines (if the user specified any); otherwise keep all.
4. Save all results to a JSON file and print a readable summary per query.
5. If the user wants a summary, compute per-query min price and per-airline hit counts.

## Example
See `scripts/gf_sweep_v2.py` for a generic CLI sweeper with extra modes:
- **Morning cutoff filter**: `--cutoff 12:00` keeps only flights departing before noon (times normalized to minutes, 12h/24h both supported).
- **Round-trip mode**: `--return 2027-03-10` adds `return <date>` to the query; the script verifies the rendered page actually shows `Round trip` returning that date and warns on mismatch.
- **Batch date sweep (max 3 days)**: `--sweep-days 3` scans N consecutive days from the first `--dates` value; values outside 1..3 are rejected.
- **Cabin**: `--cabin biz` switches to Business (default `eco`); the price sanity ceiling rises from 5000 to 30000 for `biz`.
- **Built-in airline map**: recognizes 16 carriers (AS/DL/AA/WN/UA/B6/F9/NK/AC/BA/JL/HA/SY/G4/XP/LH), no need to edit a `UID` dict.
- **Dedup + layover parsing**: identical (price, dep, route, dur) cards are deduped; connecting flights report the layover airport (`via PHX`).
- **JSON output** keyed by date, each with `trip`, `return`, `cabin`, and sorted `morning` list.

Usage:
```
python gf_sweep_v2.py --origin SFO --dest SEA --cutoff 12:00 \
    --dates 2027-03-03 2027-03-05 2027-03-07 --out out.json
python gf_sweep_v2.py --dates 2027-03-03 --return 2027-03-10 --cutoff 10:00
python gf_sweep_v2.py --dates 2027-03-03 --sweep-days 3 --cutoff 11:00
python gf_sweep_v2.py --dates 2027-03-03 --sweep-days 3 --return 2027-03-10
```

## Gotchas
- **Trip type trap**: a query with `on <date>` but no explicit `return`/`one way` is treated as a round trip by Google Flights, which auto-picks a return date (observed: +4 days). The scraped prices are round-trip fares, approximately double one-way. Always state the trip type in the URL and verify it on the rendered page before reporting.
- **Timing**: Google Flights renders slowly. Always `wait_for_timeout` after navigation (~9s) and after cabin switches (~10s) before parsing.
- **No results**: check the body text for "No results ... found" and skip that query rather than parsing empty cards.
- **Anti-bot**: keep the real UA, hide `navigator.webdriver`, and use `headless=True`. If results stop appearing, retry or add small delays.
- **Airport codes**: the deep-link accepts IATA codes (`SFO`, `TYO`, `NRT`, `HND`, etc.). `TYO`/`PAR`-style metro codes work for multi-airport cities.
- **Rate limits**: for large sweeps, run in a single browser session and reuse the page; don't relaunch per query.