seen.json is the collector's memory.

Every candidate event that has ever reached a review queue is recorded here,
whether you approved it or rejected it. That is what stops a flyer you turned
down in March from reappearing in April.

It is committed to the repo on purpose: the history is visible in git, and it
needs no database. Merging the collector's pull request is what saves it.

To let one item be collected again:
    python3 run.py forget <fingerprint>

Fingerprints are listed by:
    python3 run.py status
