# warc-tracker-script

## FAQs

### store-time and lookback

- One of the first steps is determining which WARC files need download for each active collection listed in the tracking spreadsheet.

- WASAPI exposes several timestamps, including `crawl-start-time`, `crawl-time`, and `store-time`. This script uses only `store-time` for discovery and checkpointing.

- That choice is intentional: `store-time` reflects when the WARC is actually available in WASAPI, and it can be later than the crawl-related timestamps. Since this script is about backup tracking rather than crawl tracking, `store-time` is the safest single clock to follow.

- The per-collection local state stores one checkpoint value:
  - `enumeration_checkpoint_store_time_max`

- On each run, the script:
  - reads that saved checkpoint
  - subtracts 30 days from it
  - queries WASAPI with `store-time-after=<checkpoint minus 30 days>`

- On a first run, when no checkpoint exists yet, the script uses `now` as the reference point and still subtracts 30 days.

- Why keep the 30-day overlap window?

- The overlap protects against incomplete or interrupted enumeration and download work.

- Example:

  - a run sees files with `store-time` values of Feb-02, Feb-04, and Feb-06
  - the script successfully enumerates all three files
  - but a later step fails before every needed file is downloaded or before all local state is updated as intended

- If the next run queried only for files strictly after Feb-06, it could miss a file that should still be retried.

- By querying again from 30 days before the saved checkpoint, the script deliberately re-sees a recent slice of already-known records. That overlap is then made safe by local filename-based state and deduplication logic.

- In short, the 30-day window is a recovery buffer: it reduces the chance that a partial run or transient failure causes the script to permanently skip a WARC that should have been backed up.

---

## Current module responsibilities

- `main.py` remains a thin entry point that loads config, configures logging, opens an authenticated `httpx.Client`, and iterates collection jobs.
- `lib/orchestration.py` processes collections sequentially.
- `lib/collection_sheet.py` loads active collection jobs from the spreadsheet.
- `lib/local_state.py` loads and saves `state.json` atomically and records durable[^durable] per-file download/fixity outcomes.
- `lib/wasapi_discovery.py` performs production WASAPI discovery with overlap-window checkpoint logic.
- `lib/storage_layout.py` derives year/month partitions from WARC filenames and computes planned WARC/fixity destinations.
- `lib/downloader.py` streams WARC files, writes to `*.partial`, removes stale partial files on retry, and atomically renames successful downloads into place.
- `lib/fixity.py` computes SHA-256 and writes `.sha256` and `.json` sidecars for successfully downloaded WARCs.

[^durable]: Here, durable means the recorded outcomes are meant to survive process exits, crashes, and later reruns because they are written into `state.json` on disk, not just kept in memory for the current execution.

---

