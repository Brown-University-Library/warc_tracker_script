# Plan (v05): simplified `warc_backup_script`

## Executive intent
Build a **cron-triggered, idempotent** Python script that:

1. Reads the Google Sheets tracking spreadsheet to find **Active** Archive-It collections.
2. Queries Archive-It **WASAPI** for each active collection to discover new WARC files.
3. Downloads missing WARCs to local storage.
4. Writes local **SHA-256 fixity** data for each downloaded file.
5. Updates the tracking spreadsheet at a small number of key checkpoints.

This version intentionally keeps the design simple while preserving a small `Trio` concurrency model with **two dedicated download workers** and a **separate sheet updater**:

- **Download worker 1:** downloads files from a shared job queue
- **Download worker 2:** downloads files from a shared job queue
- **Sheet updater:** writes spreadsheet progress and summary updates

The local filesystem state is the source of truth. The spreadsheet is mainly a reporting and control surface.

---

## Implementation status snapshot

Completed so far:

- configuration/env-var loading exists in `main.py`
- logging is configured in `main.py` for both console output and a predictable file location at `logs/warc_tracker_script.log`
- spreadsheet ingestion with header detection and canonical field mapping exists in `lib/collection_sheet.py`
- per-collection local `state.json` handling exists in `lib/local_state.py`
- WASAPI discovery helpers exist in `lib/wasapi_discovery.py`, including `store-time` overlap-window boundary computation, paginated record enumeration, and max `store-time` tracking
- local WARC/fixity path-building helpers exist in `lib/storage_layout.py`, including year/month partition extraction from WARC filenames and planned destination/sidecar path construction
- a temporary investigative WASAPI metadata-capture script exists in `tmp_inspect_collection_wasapi.py`
- focused `unittest` coverage exists for the sheet-ingestion, local-state, production WASAPI-discovery helpers, and temporary WASAPI-inspection helpers
- a sequential production orchestration flow exists across `main.py` and `lib/orchestration.py`; it loads active collection jobs, opens an authenticated `httpx.Client`, processes collections one at a time, runs WASAPI discovery, updates the enumeration checkpoint on successful discovery, computes planned local WARC/fixity paths for discovered filename-bearing records, and logs pending download candidates
- Archive-It credential loading and storage-root resolution exist in `lib/orchestration.py`
- focused `unittest` coverage exists for the sheet-ingestion, local-state, storage-layout helpers, production orchestration helpers, `main.py`, production WASAPI-discovery helpers, and temporary WASAPI-inspection helpers

Not yet implemented in the production backup flow:

- downloader with temp-file then atomic rename
- SHA-256/fixity writing
- Trio orchestration and spreadsheet updater flow
- durable file-manifest updates beyond the enumeration checkpoint
- spreadsheet write/update behavior
- Trio orchestration with two dedicated download workers and a separate sheet updater

---

## Locked decisions

- Discovery clock: **`store-time` only**
- Overlap window: **30 days**
- Dedup / retry basis: **local manifest keyed by filename**
- File type for MVP: **WARC only**
- Concurrency model: **Trio with 2 dedicated download workers + 1 sheet updater**
- Database: **no database for MVP**
- Spreadsheet role: **reporting/control, not correctness**

---

## Spreadsheet assumptions

The workbook currently has a collection-level worksheet that the script must tolerate even if:

- the header row is not the first row
- column order changes
- headers contain minor formatting drift such as trailing spaces

The script should normalize the sheet into a simple internal collection record structure so the rest of the pipeline does not depend on sheet layout.

For MVP, only the **collection-level** worksheet matters.

---

## Active collections

A collection is in scope when:

- `Collection ID` is present and parseable as an integer
- `Active/Inactive == "Active"`

Recommendation for MVP:

- use a strict match on `Active`
- log unexpected values
- do not broaden matching rules yet

Each collection job should contain:

- `collection_id`
- collection name or label if available
- row reference or a way to relocate the row by `collection_id`

---

## Discovery and checkpointing

### Core rule
The script uses **only** WASAPI `store-time` to decide what is new.

If a WASAPI record is missing `store-time`, treat that as an integrity problem:

- log it
- skip using it for checkpoint advancement
- continue processing other records

### Per-collection local state
Each collection needs a small local JSON state file containing at least:

- `enumeration_checkpoint_store_time_max`
- `files` mapping keyed by filename, with values such as:
  - `status` (`downloaded` or `failed`)
  - `last_attempt_at`
  - `error_count`
  - optional short error summary

### How the query boundary is computed
For each collection:

1. Read `enumeration_checkpoint_store_time_max` from local state.
2. If missing, treat this as a first run and use `now` as the reference point.
3. Compute:
   - `after_datetime = reference_checkpoint - 30 days`
4. Query WASAPI with `store-time-after=<after_datetime>`.

This overlap window protects against missed files from interrupted paging or transient API problems.

### Checkpoint advancement rule
Advance the local checkpoint only when:

- WASAPI paging completed successfully
- updated local state was written durably

Download failures do **not** block checkpoint advancement, because retries come from:

- overlap-window re-enumeration
- manifest-based filename dedupe

---

## Determining what needs download

For each discovered WARC record, a download is needed if:

- the local file does not exist, or
- the local file exists but size verification fails, or
- the local SHA-256 sidecar is missing or invalid, or
- the manifest says the prior attempt failed and retry is allowed

For MVP, ignore seed-level logic and ignore non-WARC derivatives.

---

## Download strategy

### Authentication
Use Archive-It credentials from environment variables.

### HTTP behavior
Use `httpx` with:

- streaming download
- reasonable timeout values
- retry with backoff for transient failures

### File-write behavior
For MVP:

1. Download to `*.partial`
2. On success, rename atomically to the final filename
3. Compute SHA-256
4. Write fixity sidecar
5. Update local manifest

If interrupted, leave the partial file and delete/retry it on the next run.

Do not implement HTTP range-resume in MVP.

---

## Local storage layout

Use a simpler layout than earlier drafts.

```text
{root}/collections/{collection_id}/
  warcs/
    {yyyy}/
      {mm}/
        {filename}
  fixity/
    {yyyy}/
      {mm}/
        {filename}.sha256
        {filename}.json
  state.json
```

Notes:

- Keep all files for a collection together.
- Use a simple year/month path partition derived from the WARC filename timestamp.
- Do not add more complex sharding or crawl-specific folders in MVP.

### Fixity artifacts
For each downloaded WARC:

- compute **SHA-256**
- write `{filename}.sha256` with standard checksum-line format
- write `{filename}.json` with lightweight metadata:
  - sha256
  - size
  - source URL
  - relevant timestamps

No BagIt, OCFL, or remote checksum comparison in MVP.

---

## Spreadsheet updates

Keep spreadsheet writes more frequent than the prior simplified draft, but still controlled.

### When to write
For each collection:

1. Write an **In Progress** marker when processing begins.
2. Write progress updates during downloading.
3. Write a final summary update when processing finishes.
4. Clear the In Progress marker at the end.

For MVP, progress updates should be triggered by completed downloads and flushed in small batches, for example:

- after each completed file, or
- after every small batch of completed files, or
- after a short time interval if downloads are still in progress

This gives better visibility without making the sheet the source of truth.

### What to write
At collection level, update only a small set of fields if present:

- `Server File path- collection level`
- `Last WASAPI fetch`
- `File Count ?`
- `Total Size`
- `In Progress marker`

### Quota handling
The sheet updater should:

- batch writes where practical
- retry on `429` with backoff
- allow frequent progress writes, but coalesce them when several download events arrive close together

---

## Local state model

Use a filesystem-based state directory only.

Per collection, `state.json` should hold:

- last successful enumeration checkpoint
- filename manifest with status and retry info
- last sheet update time if useful
- last error summary if useful

Optionally generate a simple `run_id` for logging and sheet traceability, but do not require a separate per-run JSON artifact in MVP.

For concurrent download logging, each download worker should also have a stable short label and include the current filename in log context.
A human-friendly combined display label such as `w1:filename` or `w2:filename` should be used in download-related logs so interleaved worker output remains easy to follow.

---

## Trio architecture: Option 1

The current codebase does **not** implement this Trio architecture yet. The production flow is currently a simpler sequential orchestrator that performs discovery and checkpoint persistence only.

Retain a simple `Trio` design with:

- **two dedicated download workers**
- **one separate sheet-updater task**
- **one main orchestrator** that performs sheet ingestion, collection selection, WASAPI discovery, and job submission

### Main orchestrator
This task:

1. loads sheet data
2. selects active collections
3. processes collections one at a time
4. queries WASAPI
5. decides what needs download
6. submits download jobs to a shared queue
7. receives completion information from download workers
8. updates local state
9. sends spreadsheet update events to the sheet updater

### Download worker 1 and Download worker 2
Each worker:

1. receives a file-download job from the shared queue
2. downloads to `*.partial`
3. renames atomically on success
4. computes SHA-256 and writes fixity sidecars
5. emits a success or failure event back to the orchestrator
6. writes download-related logs using a combined display label such as `w1:filename` or `w2:filename`

### Sheet updater
This task:

1. receives update events from the orchestrator
2. batches writes where appropriate
3. rate-limits and retries spreadsheet writes
4. records start, progress, and final collection-level status updates

### Why this is enough
This preserves the main benefit of concurrency:

- up to two files can download concurrently
- sheet writes are paced separately from download throughput

But it avoids the extra complexity of:

- larger worker pools
- per-collection nurseries
- separate limiters for several work types
- richer event taxonomies than are needed for MVP

---

## Operational hardening

For cron use:

- use a lock so runs do not overlap
- log to a predictable location
- make configuration available through env vars and a small config surface
- ensure credentials are available to the cron environment

Keep this minimal and practical.

---

## MVP implementation sequence

1. [x] Define configuration and required env vars.
2. [x] Implement spreadsheet ingestion with header detection and canonical field mapping.
3. [x] Implement per-collection local `state.json`.
4. [x] Implement WASAPI discovery helpers with `store-time` plus 30-day overlap.
5. [x] Integrate sheet ingestion, local state, and WASAPI discovery into the current sequential production orchestration flow.
6. [x] Implement local path building using the year/month collection layout.
7. Implement downloader with temp-file then atomic rename.
8. Implement SHA-256 sidecar writing.
9. Implement the `Trio` flow:
   - main orchestrator
   - download worker 1
   - download worker 2
   - sheet updater
10. Implement spreadsheet write/update behavior.
11. Add lock and cron wrapper.
12. Run on a small set of collections before scaling up.

---

## Explicitly deferred from MVP

These items are intentionally postponed:

- seed-level tracking
- derived file types such as WAT/WANE
- sqlite
- resume via HTTP range requests
- complex directory sharding
- semantic crawl-specific directory trees beyond the simple year/month layout
- remote checksum comparison
- frequent per-file spreadsheet updates
- multiple concurrent download workers
- richer async orchestration beyond the 2-process Trio model

---
