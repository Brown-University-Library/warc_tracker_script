# Plan (v05): simplified `warc_backup_script`

## Executive intent
Build a **cron-triggered, idempotent** Python script that:

1. Reads the Google Sheets tracking spreadsheet to find **Active** Archive-It collections.
2. Queries Archive-It **WASAPI** for each active collection to discover new WARC files.
3. Downloads missing WARCs to local storage.
4. Writes local **SHA-256 fixity** data for each downloaded file.
5. Updates the tracking spreadsheet at a small number of key checkpoints.

This version intentionally keeps the design simple while preserving a **2-concurrent-process Trio flow**:

- **Process 1:** collection discovery + file download work
- **Process 2:** spreadsheet update worker

The local filesystem state is the source of truth. The spreadsheet is mainly a reporting and control surface.

---

## Locked decisions

- Discovery clock: **`store-time` only**
- Overlap window: **30 days**
- Dedup / retry basis: **local manifest keyed by filename**
- File type for MVP: **WARC only**
- Concurrency model: **Trio with 2 concurrent processes**
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
    {filename}
  fixity/
    {filename}.sha256
    {filename}.json
  state.json
```

Notes:

- Keep all files for a collection together.
- Do not add sharding, crawl folders, or date folders in MVP.
- Add those only if scale proves they are necessary.

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

Keep spreadsheet writes minimal.

### When to write
For each collection:

1. Write an **In Progress** marker when processing begins.
2. Write a final summary update when processing finishes.
3. Clear the In Progress marker at the end.

That is enough for MVP.

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
- avoid per-file writes unless later proven necessary

---

## Local state model

Use a filesystem-based state directory only.

Per collection, `state.json` should hold:

- last successful enumeration checkpoint
- filename manifest with status and retry info
- last sheet update time if useful
- last error summary if useful

Optionally generate a simple `run_id` for logging and sheet traceability, but do not require a separate per-run JSON artifact in MVP.

---

## Trio architecture: keep 2 concurrent processes

Retain a simple `Trio` design with exactly two concurrent processes/tasks:

### Process 1: collection worker
This process:

1. loads sheet data
2. selects active collections
3. processes collections one at a time
4. queries WASAPI
5. decides what needs download
6. downloads files
7. updates local state
8. sends spreadsheet update events to Process 2

### Process 2: sheet updater
This process:

1. receives update events from Process 1
2. batches writes where appropriate
3. rate-limits and retries spreadsheet writes
4. records final collection-level status updates

### Why this is enough
This preserves the main benefit of concurrency:

- file/network work can continue while sheet writes are paced separately

But it avoids the extra complexity of:

- multiple download workers
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

1. Define configuration and required env vars.
2. Implement spreadsheet ingestion with header detection and canonical field mapping.
3. Implement per-collection local `state.json`.
4. Implement WASAPI discovery with `store-time` plus 30-day overlap.
5. Implement local path building using the simple collection layout.
6. Implement downloader with temp-file then atomic rename.
7. Implement SHA-256 sidecar writing.
8. Implement the 2-process Trio flow:
   - collection worker
   - sheet updater
9. Add lock, logging, and cron wrapper.
10. Run on a small set of collections before scaling up.

---

## Explicitly deferred from MVP

These items are intentionally postponed:

- seed-level tracking
- derived file types such as WAT/WANE
- sqlite
- resume via HTTP range requests
- complex directory sharding
- semantic crawl/date directory trees
- remote checksum comparison
- frequent per-file spreadsheet updates
- multiple concurrent download workers
- richer async orchestration beyond the 2-process Trio model

---
