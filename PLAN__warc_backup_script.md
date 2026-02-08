# Plan: `warc_backup_script` (cron-triggered WARC backup + tracking-sheet updates)

## Executive intent

Build a **cron-triggered, idempotent** Python script that:

1. Reads a Google Sheets “tracking spreadsheet” to find **Active** Archive‑It collections.
2. For each active collection, queries Archive‑It’s **WASAPI** to identify **new WARC files after a computed checkpoint date/time**.
3. Downloads any missing WARCs to local storage using a **pairtree-like / sharded directory strategy** designed for very large file counts.
4. Writes **fixity information** alongside downloaded WARCs.
5. Updates the tracking spreadsheet frequently enough to preserve recoverability, but in a way that respects Sheets API quotas.

This plan assumes an **initial synchronous** implementation that later evolves into a **Trio + nursery** pipeline with controlled concurrency.

---

## Current tracking-spreadsheet structure (what the script must tolerate)

The workbook currently has two worksheets:

- **At Collection Level** (authoritative “control table”; each row is a collection)
- **At Seed Level** (optional / experimental; seed+crawl tracking)

Important drift-tolerance constraints:

- The header row is not necessarily the first row; there may be explanatory rows above it.
- Column order may change; columns may be added/removed.
- Some headers may include subtle formatting differences (e.g., trailing spaces).

Operationally, the script should ingest the sheet into a **canonical internal schema** (dicts/lists) so the rest of the pipeline does not care about column positions.

---

## Key concepts and state

### Identifiers / keys

- **Collection**: `collection_id` is the canonical key.
- **Seed-level (optional)**: `collection_id + seed_id (+ crawl_id)`.

### Checkpointing (the “after X date” problem)

The script needs a checkpoint per collection, used to request only “newer” WARC files from WASAPI.

Candidate checkpoint sources, ordered by preference:

1. **A durable local manifest** (recommended): last successful store-time/crawl-start processed for that collection (or last downloaded WARC filename).
2. **Tracking sheet**: `Last WASAPI fetch` (collection-level) and optionally `Last Fetch` (seed-level).
3. **Fallback**: a configured date like “N days back” for first run, to avoid downloading the entire historical archive unintentionally.

Design goal: checkpointing should guarantee **idempotency** and support **safe retry** after interruption.

---

## Determine active collections

### Inputs (collection-level sheet)

A row is in-scope if:

- `Collection ID` is non-empty and parseable as an integer
- `Active/Inactive == "Active"` (exact string match)

### Output of this phase

A list of “collection jobs” containing:

- `collection_id`
- collection-level metadata (repository, url, name) for logging
- spreadsheet row reference for later updates (row number, or a stable key to re-locate row by collection_id)

### Decisions / questions

- **Do you want the script to treat unexpected values** (e.g., “ACTIVE”, “Yes”, “1”) as Active?  
  Recommendation: start strict (“Active” only), log warnings for other values, and broaden later if needed.

---

## Determine the check-for-files-after-x-date

### What WASAPI can filter on (conceptually)

WASAPI responses include timestamps such as:

- `crawl-start` (start of crawl job)
- `crawl-time` (creation time of the file)
- `store-time` (deposit time into storage)

The script must choose which timestamp best represents “new since last run”.

### Recommended checkpoint rule (initial)

Use a per-collection checkpoint based on **WASAPI `store-time`** (or `crawl-time` if store-time is missing) because it most closely tracks “available for download”.

- `after_datetime = max(local_state.last_store_time, sheet.last_wasapi_fetch_as_datetime)`
- If neither exists: `after_datetime = NOW - INITIAL_LOOKBACK_DAYS` (configurable)

### Refinement for later

If you find that `store-time` can be delayed or arrives out of order, store both:

- `last_seen_store_time` (max)
- `last_seen_filename_set` for the newest store-time window

This prevents missing late-arriving files that have older timestamps.

### Decisions / questions

- Do you want the “after” filter to be **inclusive or exclusive**?  
  Recommendation: treat it as **exclusive** (after strictly) and also dedupe by filename to be safe.

- Do you want checkpoints in the sheet to be **date-only** or **date-time**?  
  Recommendation: store date-only in the sheet for humans, but keep date-time in local state for precision.

---

## Query the API to determine which files need to be downloaded

### APIs involved

1. **Archive-It WASAPI** for file discovery and download locations.
2. Optionally, **Archive-It Partner API** (seed count, crawl metadata), depending on what you want to track.
3. Optionally, **Internet Archive item metadata API** for remote checksums if you rely on the backup location.

### Minimal discovery flow (collection-scoped)

For each active collection:

1. Call WASAPI endpoint with:
   - `collection=<collection_id>`
   - `store-time-after=<after_datetime>` (or `crawl-start-after` as a fallback)
2. Page through results until exhausted:
   - Use `page` / `page_size` or follow `next` links.

For each result file record, capture:

- `filename`
- `size` (bytes, if provided)
- `crawl` (crawl job id, if provided)
- timestamps (`crawl-start`, `crawl-time`, `store-time`)
- `locations[0]` primary download URL (Archive‑It storage)
- `locations[1]` backup download URL (archive.org), if present

### Determining “needs download”

A file needs download if one of the following is true:

- Local WARC file path does not exist, OR
- Local file exists but **size mismatch**, OR
- Local fixity sidecar exists but does not verify, OR
- Prior attempt exists in local manifest marked failed and retry policy allows it

### Decision / questions

- Do you want to download **only WARC** files, or also derived datasets (WAT/WANE/LGA)?  
  Recommendation: start with WARC only; add derived types later behind a feature flag.

- Do you want to use **seed-level** logic to filter?  
  Recommendation: not initially—start collection-level and optionally populate seed-level as a reporting surface.

---

## Downloading the files

### Authentication

WASAPI access typically uses HTTP Basic Auth. Decide where credentials live:

- Environment variables (e.g., `ARCHIVEIT_USER`, `ARCHIVEIT_PASS`)
- A config file readable only by the cron user
- `.netrc` (works well with curl/wget; for Python you can still read it)

Recommendation: environment variables via a locked-down systemd/cron environment, with a dedicated service account.

### HTTP client strategy

- Use streaming downloads with `httpx`, writing to a temporary file.
- Set timeouts and retries with exponential backoff on 5xx / connection issues.
- Confirm expected file size (from WASAPI metadata or HTTP headers) before finalizing.

### Atomicity + resumability

Initial version (simpler):

1. Download to `*.partial` in the final directory.
2. On success:
   - fsync (optional)
   - rename to final filename (atomic on same filesystem)
3. If interrupted:
   - leave partial file; on next run delete/retry.

Later version (more robust):

- Support HTTP range requests if the server supports it, to resume partial downloads safely.
- Store per-file “download state” in local manifest or sqlite.

### Throttling / concurrency

Start synchronous (1 file at a time), but structure code so you can later switch to Trio.

For the eventual Trio version:

- **One nursery per collection** (or per run) spawning file download tasks.
- A `CapacityLimiter` to cap concurrent downloads (e.g., 3–10).
- A separate limiter for WASAPI queries (to avoid hammering).

---

## Saving files and fixity information locally

### Storage goals

- Must scale to “many, many files” without huge single directories.
- Must remain **human-navigable** by collection / seed / crawl / date.
- Must make it obvious which fixity data corresponds to which WARC.

### Recommended directory layout (pairtree-like + semantic)

**Root** (config): `WARC_BACKUP_ROOT`

Then:

```
{root}/collections/
  {collection_shard}/{collection_id}/
    metadata/
    warcs/
      {yyyy}/{mm}/{dd}/
        {crawl_id_or_job}/
          warc/
            {filename}
          fixity/
            {filename}.sha256
            {filename}.json
```

Where:

- `collection_shard` is a numeric sharding scheme (e.g., `000/123/456` for collection_id `123456`) to avoid too many collection directories in one folder.
- `yyyy/mm/dd` is derived from `crawl-start` (preferred) or `store-time`.
- `crawl_id_or_job` is the crawl job id (if present) or a normalized timestamp string.

This approach keeps paths discoverable, while distributing files across many directories.

### Fixity artifacts

For each downloaded WARC:

1. Compute **SHA‑256** (primary fixity).
2. Write sidecars in a `fixity/` directory adjacent to the `warc/` directory:
   - `{filename}.sha256` (one-line: `<sha256>  <filename>`)
   - `{filename}.json` including:
     - sha256, size, timestamps
     - source URL used
     - HTTP headers (ETag, Last-Modified) if available
     - optional remote checksums (md5/sha1) if you later query them

Additionally (optional but useful):

- A per-crawl manifest: `manifest-sha256.txt` listing all files and hashes in that crawl folder.

### Decision / questions

- Do you need **bagit** / OCFL / some higher-level packaging?  
  Recommendation: not initially. Your layout plus fixity sidecars gives immediate value; you can migrate to OCFL later if desired.

- Which checksum should be “canonical”?  
  Recommendation: SHA‑256 locally; store remote MD5/SHA1 only as supplemental.

---

## Updating the tracking spreadsheet

### Read strategy

At start of run:

- Read the full used range of the relevant sheets in as few API calls as practical.
- Build an internal map:
  - `collection_id -> row_index`
  - (optional) `collection_id+seed_id(+crawl_id) -> row_index`

### Write strategy: frequent but quota-safe

Constraints:

- Sheets API has per-minute read/write quotas; you must batch and pace updates.

Recommended approach:

1. Maintain an in-memory list of “pending cell updates”.
2. Flush updates:
   - after each downloaded file **OR** after N files/seconds, whichever first,
   - but using **batchUpdate** calls so one API call updates many cells.
3. Implement a token-bucket or time-based limiter for write calls.
4. On `429 Too Many Requests`:
   - exponential backoff, then retry.

### What to update (collection level)

After processing a collection (or periodically during):

- `Server File path- collection level` (if empty or changed)
- `Last WASAPI fetch` (date string, set when you complete processing; optionally also write “in progress” markers elsewhere)
- `Total Size` (human-readable, or bytes normalized later)
- `File Count ?` (count of locally-present WARCs for the collection)
- `Seed Count` (if you query seeds; otherwise leave unchanged)

### What to update (seed level) — optional

Only if you decide seed-level tracking is valuable early:

- For each crawl/seed bucket processed:
  - `# of WARCs`
  - `First Fetch` (if empty)
  - `Last Fetch`
  - `Files22 Filepath`
  - `Status`

### Operational recoverability

To reduce divergence between reality and sheet:

- Write updates at least:
  - after each collection finishes, and
  - after every N files within that collection (configurable, e.g., 10)

If you keep a **local manifest** as the true state, the sheet becomes a reporting/control plane and can lag slightly without harming correctness.

### Decision / questions

- Is `Active/Inactive` writable by automation?  
  Recommendation: treat it as **staff-controlled read-only** unless you have a clear workflow for auto-pausing failing collections.

---

## Local state management without a database (recommended baseline)

To avoid a database while maintaining idempotency and fast restarts, create a local “state directory”:

```
{root}/_state/
  run-lock/
  collections/
    {collection_id}.json
  runs/
    {timestamp}.json
```

Per-collection state JSON should include:

- last successful checkpoint (store-time/crawl-time)
- last successful sheet update time
- a record of recently downloaded filenames (bounded list)
- failure counters / last error summary

Per-run log JSON should include:

- start/end times
- counts downloaded, bytes, failures
- list of collections touched

This provides durable state for:

- “download once” semantics
- debugging and audit trail
- future async orchestration

---

## What sqlite would simplify (if you decide to allow it later)

SQLite would help with:

- High-volume dedupe (filename -> status) without reading large JSON files
- Concurrency coordination (multiple workers)
- Rich reporting (failed downloads, retries, bytes per collection)
- “Exactly-once” semantics with robust transactional updates

If you stay no-DB, you can still get most benefits with:

- append-only JSONL events + periodic compaction
- per-collection manifests

---

## Synchronous now, Trio later (architecture that supports both)

### Proposed pipeline stages

1. **Load sheet snapshot** → canonical internal records
2. **Select active collections**
3. For each collection:
   1. compute checkpoint
   2. query WASAPI → list of candidate files
   3. filter to “needs download”
   4. download + verify + write fixity sidecars
   5. update local manifest
   6. enqueue sheet updates
4. Flush sheet updates (batched)
5. Write run summary

### Trio evolution

- Replace the “for each file” loop with:
  - a nursery for download tasks
  - a `MemoryChannel` or in-memory queue for “download completed” events
- Have one task dedicated to sheet updates:
  - consumes completion events, batches, rate-limits, writes

This cleanly separates:

- high-throughput downloading
- low-throughput API writes

---

## Cron concerns (operational hardening)

- Use a lock (e.g., `flock`) so runs do not overlap.
- Log to a predictable location (and rotate).
- Emit a concise “run summary” (counts + errors) suitable for email/Slack later.
- Ensure credentials are available in the cron environment.
- Make runtime configurable via a config file plus env overrides.

---

## Open questions / decisions to resolve before implementation

1. **Checkpoint semantics**
   - Use store-time-after vs crawl-start-after?
   - How to handle late-arriving backup copies?

2. **Seed-level tracking**
   - Is it required for MVP, or can it be populated later?

3. **Fixity source of truth**
   - SHA-256 only locally, or also compare against remote MD5/SHA1 where possible?

4. **File layout**
   - Confirm the preferred “semantic” path keys (collection/seed/crawl/date), and whether sharding by collection id is acceptable.

5. **Sheet update frequency**
   - Target a max write rate (e.g., ≤ 30 batch writes/min) and choose flush intervals accordingly.

6. **Error policy**
   - When should a collection be marked “Error” (seed-level) or skipped on subsequent runs?
   - How many retries and what backoff?

---

## Concrete next step checklist (implementation-ready, still no code)

1. Decide configuration surface (env vars + config file) and required secrets.
2. Implement sheet ingestion that:
   - detects header row by name matching
   - maps to canonical internal schema
3. Implement per-collection local state file.
4. Implement WASAPI query wrapper:
   - filters by collection and checkpoint time
   - handles pagination robustly
5. Implement deterministic local path builder.
6. Implement downloader:
   - temp file → atomic rename
   - sha256 sidecar writing
7. Implement batched sheet updater with write rate limiting.
8. Add cron wrapper + lock + logging.
9. Dry-run mode (no downloads; only reports planned actions).
10. Run on a small subset of collections; validate end-to-end; then scale.

---
