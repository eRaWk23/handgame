# Handgame event collector

Finds handgame, stickgame and bone game flyers around the web, reads the dates
off them, checks them against what is already on handgame.info, and puts what
is left in a review queue for a human to approve.

Nothing it finds is published automatically. Every event passes through a
person first.

```
sources ─┬─ calendar feeds (WordPress / iCal)
         ├─ tribal, casino and powwow websites
         ├─ Reddit
         ├─ open web search
         └─ inbox/  (Facebook and Instagram flyers you drop in)
              │
              ▼
      read the flyer  (Tesseract, then Claude vision if a key is set)
              │
              ▼
      pull out date, place, tribe, contact
              │
              ▼
      three duplicate checks
        1. seen in an earlier run?          (state/seen.json)
        2. same flyer image?                (perceptual hash)
        3. same real event, different words? (fuzzy date + place + title)
              │
              ▼
      out/review.html  ──►  you approve  ──►  Supabase `events` table
```

## Quick start

```bash
cd scraper
pip install -r requirements.txt
sudo apt-get install tesseract-ocr        # macOS: brew install tesseract

export SUPABASE_URL="https://yourproject.supabase.co"
export SUPABASE_ANON_KEY="your-publishable-key"

python3 run.py scrape
open out/review.html
```

The review page shows each event next to its flyer. Fix anything the reader
got wrong, hit Approve or Reject, then either **Publish approved to site**
(inserts straight into Supabase) or **Download approved.json** and run
`python3 run.py publish approved.json`.

## Commands

| Command | What it does |
|---|---|
| `run.py scrape` | Collect, dedupe, write `out/review.html` |
| `run.py scrape --only calendars` | Run one source |
| `run.py scrape --dry-run` | Collect but write nothing |
| `run.py publish approved.json` | Insert reviewed events into Supabase |
| `run.py status` | What the ledger remembers |
| `run.py forget <fingerprint>` | Let a rejected item be collected again |

## Running it on a schedule

`.github/workflows/scrape-events.yml` runs on the 1st and 15th of each month
and opens a pull request when it finds something. The review queue is attached
to the run as a downloadable artifact.

Add these under **Settings → Secrets and variables → Actions**:

| Secret | Needed? | What it buys you |
|---|---|---|
| `SUPABASE_ANON_KEY` | yes — **already set in this repo** for keep-alive.yml | Comparing finds against live events |
| `SUPABASE_URL` | no | Falls back to the project URL already public in `supabaseClient.js` |
| `ANTHROPIC_API_KEY` | recommended | Reads stylized flyers far better than OCR alone |
| `BRAVE_SEARCH_API_KEY` *or* `SERPER_API_KEY` | optional | Finds sites not yet in `config.yaml` |
| `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` | optional | Turns the Reddit source on |

Merging the pull request is what saves the ledger. Until you merge, the same
events can surface again next run.

## About Facebook and Instagram

Most handgame flyers get posted to Facebook. There is no honest way to scrape
it: Meta blocks automated traffic, requires a logged-in session, and forbids
collection in its terms. A scraper that claimed to do it would just return
nothing every run and you would not know why.

So that path is manual on one end and automatic on the other. Save a flyer out
of a post into `scraper/inbox/` and the next run treats it like any other
source — OCR, date extraction, duplicate checks, review queue. Or put URLs in
`inbox/links.txt`, one per line.

If you administer a Facebook Page or Group that posts events, the Graph API
can read its own events legitimately with a page token. That is worth wiring
up if it applies to you; it is the one supported route in.

## Adding a source

Point the collector at more sites by editing `config.yaml`:

```yaml
  calendars:
    sites:
      - url: https://newtribe.example
        tribe: Example
        location: Somewhere, WA
```

Add the same site under `webpages` too. `calendars` tries the machine-readable
feeds, which are exact; `webpages` reads the HTML when there is no feed.

A whole new *kind* of source is one class in `handgame_scraper/sources/` with a
`collect()` method that yields `Event` objects, registered in
`sources/__init__.py`. Everything downstream is shared.

## Tuning

In `config.yaml` under `settings`:

- **`min_topic_score`** (0–1, default 0.5) — how sure the collector must be
  that a page is about handgame. Raise it if the queue has junk in it; lower it
  if real events are being missed.
- **`request_delay_seconds`** (default 2.0) — pause between requests to the
  same site. Please do not lower this; many of these are small community
  servers.
- **`max_flyers_per_run`** (default 120) — cap on flyer downloads per run.
- **`use_vision_ocr`** — set false to skip the API even when a key is present.

## How duplicates are caught

Three independent checks, because each misses cases the others catch:

1. **The ledger** (`state/seen.json`) remembers every candidate ever queued,
   approved or rejected. Something you turned down in March will not come back
   in April. It is plain JSON in git, so its history is visible.
2. **Perceptual image hashing** catches the same flyer reposted at a different
   size or quality — distance 0 across a 50% resize and heavy recompression in
   testing. If the same artwork shows up with a *different* date, it is flagged
   rather than dropped, because hosts reuse last year's poster.
3. **Fuzzy field matching** catches the same event described differently.
   "Colville Labor Day Stickgame Tournament" and "38th Annual Labor Day Hand
   Game Tourney" in Nespelem on the same weekend score as one event. Two
   tournaments on the same day in different states do not, even when both are
   called "Handgame Tournament".

Near-certain matches merge silently. Plausible ones are queued with a note
naming the event they resemble, so you decide.

### Community flags

`script.js` hides an event once `report_count` reaches 3. The collector reads
that column and treats a flagged-down event as still being on the site, so it
is never re-added — otherwise every run would put back whatever the community
just voted off. Those are counted separately in the run summary as "flagged off
by the community" rather than blending into ordinary duplicates, and a
candidate that merely *resembles* a flagged event is queued with a warning
instead of being dropped.

`REPORT_THRESHOLD` in `handgame_scraper/supabase.py` mirrors the one in
`script.js`. If you change one, change the other.

## Tests

```bash
python3 tests/test_core.py       # dates, places, dedup, ledger
python3 tests/test_adapters.py   # each source against canned pages
python3 tests/test_pipeline.py   # a flyer on disk to a reviewable event
python3 tests/test_regressions.py  # bugs found in review, kept fixed
```

Only the pipeline test needs anything installed beyond the requirements
(Tesseract); the rest need no network and no services. 177 assertions.

## What is deliberately conservative

An event with no date, or no location, never reaches the queue — the site
requires both, and a half-filled listing is worse than none. Dates that could
be read two ways ("9/12") are queued with a warning instead of a guess. A year
printed on a flyer always beats a year the parser inferred. When the collector
is unsure, it says so rather than deciding for you.
