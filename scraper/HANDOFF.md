# Handoff: handgame.info event collector

Written for whoever picks this up next, human or Claude Code. Read the
**Landmines** section before changing anything in `extract.py` or `dedupe.py`.

---

## 1. What this is

An automated collector that finds handgame / stickgame / bone game event
flyers on the web, reads the dates off them, checks them against what is
already in the site's Supabase table, and produces a review queue. A human
approves each event before it is published. Nothing publishes on its own.

It lives in `scraper/` inside the `eRaWk23/handgame` repo, alongside the
static site. It does not touch any of the site's existing files.

## 2. Current state

- Branch: **`add-event-collector`**, 33 files, additions only.
- Nothing pushed yet at time of writing — check `git log origin/main..HEAD`.
- All four test suites pass: 61 + 44 + 26 + 46 = **177 assertions**.
- **Never run against the live site yet.** Every network adapter is tested
  against fixture documents only, because the environment it was built in had
  no outbound web access. First real run is the real test — expect selector
  tuning on `webpages` in particular.

### First thing to do

```bash
cd scraper
pip install -r requirements.txt
export SUPABASE_URL="https://atorftwulkabkmhaeeir.supabase.co"
export SUPABASE_ANON_KEY="<the anon key, already a repo secret>"
python3 run.py -v scrape --only calendars --dry-run
```

`-v` is a global flag and must come *before* the subcommand; putting it at the
end exits 2 with "unrecognized arguments".

Start with `calendars` — it is the highest-signal adapter and the least likely
to produce noise. Then `webpages`, then the rest.

## 3. The site it feeds (facts, verified against the repo)

Static HTML on GitHub Pages, no build step, Supabase for data and storage.

**Table `events`:**
`id, title, start_date, end_date, location, tribe, details, flyer_url,
report_count, approved, created_at`

- `script.js:45-47` fetches with `.select('*')` — **no server-side filter.**
- `script.js:58` filters client-side: `report_count < REPORT_THRESHOLD` (3).
  This is the real moderation: **community flags, reactive, not pre-approval.**
- `admin.html` sets `approved: true` on a row, but **nothing reads `approved`.**
  It is currently a vestigial column. Do not "fix" this by adding
  `.eq('approved', true)` to `script.js` without first backfilling every
  existing row to `approved = true` — otherwise the whole calendar disappears.
- Storage bucket for flyers: **`event-flyers`**, public URLs.
- `submission.html` inserts exactly:
  `{title, start_date, end_date, location, tribe, details, flyer_url}`
  with required = title, start_date, location. The collector matches that
  shape deliberately.
- `.github/workflows/keep-alive.yml` already pings Supabase every 3 days and
  already uses the `SUPABASE_ANON_KEY` secret. The project URL is public in
  `supabaseClient.js`, so the collector's workflow falls back to it and needs
  **no new required secrets.**

## 4. Architecture

```
run.py                     CLI: scrape | publish | status | forget
handgame_scraper/
  models.py                Event dataclass; fingerprint / match_key; normalizers
  fetch.py                 the only HTTP path: robots.txt, throttle, cache, retry
  extract.py               dates, locations, tribes, topic scoring  ← highest risk
  ocr.py                   Tesseract, optional Claude vision, perceptual hash
  dedupe.py                similarity scoring and batch collapsing  ← highest risk
  ledger.py                state/seen.json — memory across runs
  supabase.py              read live events, insert approved ones
  pipeline.py              orchestration: collect → enrich → filter → dedupe → queue
  review.py                generates the self-contained review HTML
  sources/
    base.py                Source contract + safe_collect (swallows per-source failure)
    calendars.py           WordPress "The Events Calendar" REST + iCal   ← best quality
    webpages.py            JSON-LD, then microdata, then plain HTML
    reddit.py              official API; off without credentials
    websearch.py           Brave or Serper; off without a key
    inbox.py               manual drop folder — the Facebook/Instagram path
```

**Adding a source** = one class with `collect()` yielding `Event`, registered
in `sources/__init__.py`. Everything downstream is shared.

**The three duplicate checks** (all needed, each catches what the others miss):

1. `state/seen.json` — every candidate ever queued, approved *or rejected*.
   Rejected items must never come back; this is the only thing guaranteeing it.
2. Perceptual hash of the flyer image — catches reposts at other resolutions.
3. Fuzzy match on date + location + title — catches the same event written up
   differently by two sources.

## 5. Landmines

Bugs already found and fixed here. Each has a regression test in
`tests/test_regressions.py`. **If you refactor and a test there fails, you have
reintroduced a real bug — do not adjust the test to match.**

1. **Two-digit years.** `extract.py` accepts only 4-digit years or `'26` in
   month-day patterns. Allowing bare `\d{2}` made "AUGUST 29, 30, 31" parse as
   August 29th **2030**, with high confidence and no warning. Worst possible
   failure: a wrong date that looks clean.
2. **Printed year beats inferred year.** A year on the flyer is a fact; an
   inferred one is a guess. Do not let a "prefer future dates" rule override a
   printed year — that turned "May 22-25, 2026" into 2027.
3. **Fingerprints must include title + date, not just URL.** A listing page
   with no per-event links gave every event the same `source_url`, collapsing
   them into one ledger entry and permanently suppressing all but the last.
4. **`<header>` is stripped before parsing** and the whole-page fallback does
   not take a link, because the first `<a>` on a page is a site logo.
5. **State abbreviations match uppercase only, and the rightmost address
   wins.** Case-insensitive matching read "Lodge, La Conner, WA" as
   "Lodge, Louisiana".
6. **Only the final token of a location expands to a state.** Expanding any
   two-letter token turned "Center in Omak, WA" into "...indiana omak..." and
   silently broke duplicate detection for any location containing in/at/or/la.
7. **Identical flyer image does not override a date conflict.** Hosts reuse
   last year's artwork. Same image + different date = flag it, keep both.
8. **A community-flagged event stays in the "already on site" list.** Dropping
   flagged rows from the dedup comparison would make the collector re-add
   whatever the community just voted off, every run, forever. See
   `supabase.py: REPORT_THRESHOLD` — keep it in step with `script.js`.
9. **Supabase reads degrade, they do not raise.** A 200 carrying HTML (proxy
   error page) used to abort a run after all the fetching and OCR was spent.
10. **`publish` never aborts mid-file.** A partial publish that raises leaves
    the user unable to safely re-run without double-inserting.
11. **A printed weekday is checked against the date beside it.** Tesseract read
    the Nespelem flyer's "Thursday, July 9, 2026" as "July 7, 2026": a clean
    parse, high confidence, no warning, two days wrong. Nothing downstream
    could catch it — the date is well-formed and in range. But July 7th 2026
    is a Tuesday and the flyer says Thursday, so `find_dates` now warns on any
    weekday that contradicts an adjacent date. It only compares *adjacent*
    pairs (a weekday elsewhere on a listing page proves nothing) and it never
    rewrites the date — which of the two was misread is not knowable here.

## 6. Decisions made on purpose

Do not undo these without a reason:

- **No Facebook or Instagram scraper.** Meta blocks automated traffic, requires
  a logged-in session, and forbids collection in its terms. A scraper claiming
  otherwise returns nothing every run and hides its own failure. The `inbox/`
  folder is the honest path: manual on one end, fully automatic after that. If
  the site owner administers a Page, the Graph API with a page token is the one
  legitimate route and is worth adding.
- **A human approves everything.** The site has no pre-publish gate, so the
  review queue *is* the gate. Do not add a direct insert path from the
  scheduled run.
- **Events without a date or a location are dropped, not queued.** The site
  requires both. A half-filled listing is worse than none.
- **`request_delay_seconds: 2.0` and robots.txt respected.** These are small
  tribal and community web servers. Do not lower this.
- **Insert payload matches `submission.html` exactly**, with `approved: true`
  added and a retry without it if a policy rejects the column.
- **The ledger is committed to git**, not stored in a database. History is
  visible, and merging the PR is what saves it.

## 7. Known gaps / next steps

- [x] **Run it for real.** Done 2026-08-12: calendars, webpages and inbox all
      run against live sites. Both web adapters returned zero events, and that
      was the correct answer — no site in the list currently advertises a
      handgame event in text. The selectors work: Tulalip parsed 19 events
      cleanly, all correctly scored 0.00 and dropped.
- [x] **Verify the site list.** Done 2026-08-12, every domain fetched. Of 14
      "calendar" sites exactly three serve a feed (Yakama iCal, CSKT and Nez
      Perce REST); the rest were pruned with reasons recorded in config.yaml.
      Dead: `umatilla.nsn.us` (no DNS, now `ctuir.org`), Shoshone-Bannock
      (refuses :443), Crazy Crow's calendar (gone). Moved: `csktribes.org` →
      `cskt.org`, `12tribescasino.com` → `colvillecasinos.com`.
- [ ] **CTUIR has no machine-readable feed.** `ctuir.org/events/` is the
      largest listing found (29 pages) and is JavaScript-rendered, so a static
      fetch sees 804 characters and no events. `wp-json` 404s. Currently
      unreachable by any adapter; needs a rendered fetch or a different route.
- [ ] **Beware the silent empty feed.** A `wp-json` probe that returns 200 with
      an empty events list logs *nothing* — identical in the run output to a
      site with no feed at all. Nez Perce was pruned once on that mistake and
      had to be restored. Confirm a feed is absent by requesting the endpoint
      directly before removing a site.
- [ ] **Flyer mirroring is written but unused.** `supabase.upload_flyer()`
      exists; the pipeline does not call it. Remote flyers rot, and a calendar
      of broken images is bad. Worth wiring into the approve step, which needs
      the storage bucket to accept writes from the anon key.
- [ ] **Vision OCR is still untested, and Tesseract alone is not enough.**
      Five real flyers were run through `inbox/` on 2026-08-12 with no
      `ANTHROPIC_API_KEY`, so Tesseract handled them alone. All five were
      rejected: two lost their location (Redding CA and Goodfish Lake AB are
      outside `KNOWN_PLACES`), one lost its date entirely to display-font
      spacing, one lost the word "stickgame" to stylised type, and one had a
      digit misread — see landmine 11. Set `ANTHROPIC_API_KEY` before judging
      this path; the vision call at `pipeline.py:141` is wired and ready.
- [ ] **`KNOWN_PLACES` in `extract.py` is Pacific Northwest and Plateau
      heavy.** Fine for now — that is where handgame concentrates — but it will
      miss California, Great Basin, and prairie events. Extend as needed.
- [ ] **No alert when a run finds nothing for several cycles in a row.** That
      is the signature of every source quietly breaking at once.
- [ ] Consider whether `approved` should become the real gate (see §3), which
      is a site change, not a collector change.

## 8. Commands

```bash
python3 run.py scrape                    # collect, dedupe, write out/review.html
python3 run.py scrape --only calendars   # one source
python3 run.py -v scrape --dry-run       # change nothing, log everything
                                         # note: -v goes before the subcommand
python3 run.py publish approved.json     # insert reviewed events
python3 run.py status                    # what the ledger remembers
python3 run.py forget <fingerprint>      # let a rejected item come back

python3 tests/test_core.py
python3 tests/test_adapters.py
python3 tests/test_regressions.py
python3 tests/test_pipeline.py           # needs Tesseract installed
```

## 9. Environment

| Variable | Needed? | Notes |
|---|---|---|
| `SUPABASE_ANON_KEY` | yes | Already a repo secret, used by keep-alive.yml |
| `SUPABASE_URL` | no | Falls back to the URL public in `supabaseClient.js` |
| `ANTHROPIC_API_KEY` | recommended | Vision flyer reading; Tesseract alone struggles with display fonts |
| `BRAVE_SEARCH_API_KEY` / `SERPER_API_KEY` | optional | Enables the discovery source |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | optional | Enables Reddit; free "script" app |

System dependency: `tesseract-ocr`.

## 10. Context worth keeping

This is a one-person community project — no team, no sponsors — serving Native
communities across the Plateau, Plains and interior Northwest. Handgame dates
travel by flyer and word of mouth, and people drive hours on them. A wrong date
on this calendar sends someone to an empty gym.

That is the reason for the conservatism throughout: drop rather than guess,
warn rather than assume, and never publish without a person looking at it.
Keep that bias if you change anything.
