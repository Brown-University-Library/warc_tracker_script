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
- per-collection local `state.json` handling exists in `lib/local_state.py`, including atomic save/load helpers and durable per-file manifest updates for download/fixity outcomes
- WASAPI discovery helpers exist in `lib/wasapi_discovery.py`, including `store-time` overlap-window boundary computation, paginated record enumeration, and max `store-time` tracking
- local WARC/fixity path-building helpers exist in `lib/storage_layout.py`, including year/month partition extraction from WARC filenames and planned destination/sidecar path construction
- a production downloader exists in `lib/downloader.py`; it streams with `httpx`, writes to `*.partial`, removes stale partial files on retry, atomically renames successful downloads into place, and returns explicit success/failure results
- a production fixity module exists in `lib/fixity.py`; it computes SHA-256 for downloaded WARCs, writes `.sha256` and `.json` sidecars atomically, and returns explicit success/failure results
- a temporary investigative WASAPI metadata-capture script exists in `tmp_inspect_collection_wasapi.py`
- focused `unittest` coverage exists for the sheet-ingestion, local-state, production WASAPI-discovery helpers, and temporary WASAPI-inspection helpers
- a sequential production orchestration flow exists across `main.py` and `lib/orchestration.py`; it loads active collection jobs, opens an authenticated `httpx.Client`, processes collections one at a time, switches between first-run full historical backfill and checkpointed 30-day overlap-window discovery based on the local enumeration checkpoint, runs WASAPI discovery, updates the enumeration checkpoint on successful discovery, computes planned local WARC/fixity paths for discovered filename-bearing records, extracts usable source URLs, downloads WARC files sequentially to planned destinations, generates fixity sidecars after successful downloads, durably records per-file download/fixity outcomes in `state.json`, and logs per-collection download/fixity summaries
- Archive-It credential loading and storage-root resolution exist in `lib/orchestration.py`
- focused `unittest` coverage exists for the sheet-ingestion, local-state, storage-layout helpers, downloader helpers, fixity helpers, production orchestration helpers including first-run versus checkpointed discovery behavior, `main.py`, production WASAPI-discovery helpers, and temporary WASAPI-inspection helpers

Not yet implemented in the production backup flow:

- spreadsheet write/update behavior, including up-front validation of required reporting columns and collection-level start/final status writes
- Trio orchestration with two dedicated download workers and a separate sheet updater
- lock and cron wrapper hardening

---

## Locked decisions

- Discovery clock: **`store-time` only**
- First-run discovery behavior: **full historical backfill when no checkpoint exists**
- Overlap window: **30 days after the first successful checkpoint exists**
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
2. If a checkpoint exists, treat it as the reference point.
3. If no checkpoint exists, treat this as a first run and perform a full historical backfill for that collection.
4. When a checkpoint exists, compute:
   - `after_datetime = reference_checkpoint - 30 days`
5. Query WASAPI as follows:
   - on first run with no checkpoint: do not use the recent-only `now - 30 days` boundary
   - on later runs with a checkpoint: use `store-time-after=<after_datetime>`

This design ensures that a collection with no prior local backup can still reach full historical coverage, while later runs retain
the overlap-window protection against missed files from interrupted paging or transient API problems.

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

The current production code implements steps 1 through 5 in the sequential flow.

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

## Detailed design for spreadsheet status updates

This section expands the spreadsheet-update step so the project has a clearer target before implementation begins.

### Recommendation: use `processing_status_main` and `processing_status_detail` as separate spreadsheet columns

Recommendation for MVP:

- use a **per-collection** `processing_status_main` spreadsheet column
- use a separate `processing_status_detail` spreadsheet column
- do **not** use one workbook-level or whole-run status field as the primary reporting mechanism
- do **not** pack both values into one JSON string for MVP
- optionally add a lightweight whole-run log message or run summary later, but keep the sheet status centered on each collection row

Why this is the better fit:

- the script already processes work in terms of collections
- the spreadsheet’s control/reporting model is collection-centric
- collections can succeed, fail, or have no-op outcomes independently
- a single workbook-level status would become ambiguous as soon as more than one collection is processed in a run
- the future Trio design still maps naturally to collection-level status updates

### Why not a single all-processing status only

A single status for the entire run would be simpler to write, but it would not answer the operational questions that seem most useful in the sheet:

- which collection is currently being processed
- which collection had nothing new to download
- which collection failed during discovery versus downloading versus final sheet update
- which collection completed successfully but with partial download failures

So the recommendation is:

- **primary status model**: per-collection `processing_status_main` plus `processing_status_detail`
- **optional future enhancement**: separate run-level status or run-log artifact outside the collection worksheet

### Recommendation: define a bounded set of `processing_status_main` values in code

The code should define a small, explicit list of allowed `processing_status_main` values in one place.

Recommendation for MVP:

- define these as constants or an enum-like structure in code
- keep the list short and stable
- ensure every sheet write uses one of these values
- avoid ad hoc free-text `processing_status_main` values generated inline during orchestration

Proposed `processing_status_main` values:

- `pending`
  - collection was selected for this run but processing has not started yet
- `discovery-in-progress`
  - WASAPI enumeration is currently running for the collection
- `download-planning-complete`
  - discovery succeeded and the script has determined what files, if any, need download
- `downloading-in-progress`
  - one or more files are currently being downloaded or processed for fixity
- `no-new-files-to-download`
  - discovery succeeded and no downloads were needed
- `downloaded-without-errors`
  - all required downloads and fixity work completed successfully
- `completed-with-some-file-failures`
  - collection processing finished, but one or more file downloads or fixity operations failed
- `discovery-failed`
  - WASAPI discovery did not complete successfully
- `spreadsheet-update-failed`
  - collection processing may have completed, but at least one required sheet write failed
- `skipped-invalid-collection-row`
  - the row could not be processed because required collection-level source data was invalid

This list is intentionally more granular than just start/end, but still small enough to stay understandable.

### Recommendation: keep `processing_status_main` and `processing_status_detail` separate

Some statuses naturally invite extra context. Recommendation for MVP:

- keep `processing_status_main` short, stable, and enumerated
- store extra context separately in `processing_status_detail`
- require both `processing_status_main` and `processing_status_detail` worksheet columns to exist before significant processing begins

This preserves simplicity while allowing helpful operator-facing context.

### Chosen status-field approach

Use:

- one enumerated `processing_status_main` field
- one required `processing_status_detail` field with compact human-readable context

Example detail values:

- for `downloading-in-progress`: coarse progress marker plus compact progress counts, such as `20% (3/15 files)` or `60% (9/15 files)`
- for `no-new-files-to-download`: overlap-window reference such as `since 2026-02-06T00:00:00Z`
- for `completed-with-some-file-failures`: `2 of 14 files failed`
- for `discovery-failed`: short error summary

Pros:

- still simple
- operator-friendly
- avoids encoding structured data into `processing_status_main`

Cons:

- detail text may drift in format over time if not kept disciplined

Implementation note:

- use coarse, stable `processing_status_detail` formats rather than highly dynamic per-file chatter
- prefer milestone-style updates during downloading, such as `20%`, `40%`, `60%`, `80%`, and completion
- include file counts with the milestone when available

### Recommendation on validation before processing

The user preference for cron jobs to validate early is a strong fit for this project.

Recommendation for the spreadsheet-update layer:

1. validate required configuration and credentials at startup
2. validate spreadsheet connectivity before collection processing begins
3. validate required source worksheet headers before selecting active collections
4. validate that the required status-reporting worksheet columns exist before significant download work begins
5. fail early when a required field for the chosen MVP design is missing

This validation means validating the presence of the columns the code expects to write to. It does **not** mean validating every existing historical cell value in those columns before the run starts.

Recommended MVP split:

- required input fields:
  - fields needed to identify active collections and collection IDs
- required reporting fields:
  - collection-level `processing_status_main`
  - collection-level `processing_status_detail`
  - `summary_status_last_wasapi_check`
  - `summary_status_downloaded_warcs_count`
  - `summary_status_downloaded_warcs_size`
  - `summary_status_server_path`

### Required TODO if validation is not yet implemented in code

If the production code does not already validate that the required spreadsheet/worksheet status fields exist before significant processing begins, add an explicit project TODO during implementation.

That TODO should state, in substance:

- validate required status-reporting worksheet fields up front before discovery/download processing starts
- fail early with a clear error when a required field is missing
- require `processing_status_main`, `processing_status_detail`, `summary_status_last_wasapi_check`, `summary_status_downloaded_warcs_count`, `summary_status_downloaded_warcs_size`, and `summary_status_server_path` to exist before processing begins

This TODO should remain until the validation behavior exists in production code.

### Recommended collection-level status lifecycle

For better granularity than only start/end, the collection-level lifecycle should look like this:

1. `pending`
2. `discovery-in-progress`
3. `download-planning-complete`
4. one of:
   - `no-new-files-to-download`
   - `downloading-in-progress`
5. final outcome:
   - `downloaded-without-errors`
   - `completed-with-some-file-failures`
   - `discovery-failed`
   - `spreadsheet-update-failed`

This gives useful operational checkpoints without turning the sheet into a per-file event log.

During `downloading-in-progress`, `processing_status_detail` should provide coarse progress visibility rather than only repeating the phase name.

Recommended MVP convention:

- update `processing_status_detail` at coarse milestones such as `20%`, `40%`, `60%`, `80%`, and completion
- include completed/total file counts when known, for example `40% (6/15 files)`
- avoid highly chatty per-file `processing_status_detail` updates unless later experience shows they are needed

### Recommendation on write frequency

Recommendation for MVP:

- always write status when a collection enters discovery
- write status after download planning determines whether work exists
- write periodic download progress only at coarse checkpoints, using milestone-style `processing_status_detail` updates
- always write a final outcome summary

Good coarse progress examples:

- when downloading starts
- at `20%`, `40%`, `60%`, and `80%` of files completed
- when a useful milestone can be expressed as `X/Y files`
- on final completion or failure

Avoid overly chatty writes that make rate-limiting and retry behavior harder to reason about.

### Recommendation on summary fields versus status fields

Keep summary metrics separate from status.

- `processing_status_main` answers: what phase or outcome is this collection in
- `processing_status_detail` answers: what extra context is useful right now
- `summary_status_*` fields answer: what was the result of this collection run

For example:

- `processing_status_main`: `downloading-in-progress`
- `processing_status_detail`: `40% (6/15 files)`
- summary fields at finish:
  - `summary_status_last_wasapi_check`
  - `summary_status_downloaded_warcs_count`
  - `summary_status_downloaded_warcs_size`
  - `summary_status_server_path`

For this plan, all six spreadsheet columns named above are part of the required worksheet contract for the spreadsheet-update feature. If any of them are absent, the script should fail early before significant processing begins.

### Design guardrails

To preserve simplicity:

- keep the filesystem and `state.json` as the source of truth
- never require the spreadsheet to reconstruct per-file correctness
- keep the `processing_status_main` vocabulary explicit and bounded
- prefer one required `processing_status_detail` field over several structured progress columns for MVP
- validate required fields early, before expensive processing
- require the processing-status and summary-status columns up front as part of startup validation

---

## Local state model

Use a filesystem-based state directory only.

Per collection, `state.json` should hold:

- last successful enumeration checkpoint
- filename manifest with status and retry info, including durable download/fixity outcome fields
- last sheet update time if useful
- last error summary if useful

Optionally generate a simple `run_id` for logging and sheet traceability, but do not require a separate per-run JSON artifact in MVP.

For concurrent download logging, each download worker should also have a stable short label and include the current filename in log context.
A human-friendly combined display label such as `w1:filename` or `w2:filename` should be used in download-related logs so interleaved worker output remains easy to follow.

---

## Trio architecture: Option 1

The current codebase does **not** implement this Trio architecture yet. The production flow is currently a simpler sequential orchestrator that performs discovery, checkpoint persistence, planned-path construction, source-URL extraction, and sequential downloading.

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
4. [x] Update WASAPI discovery and orchestration so a collection with no checkpoint performs a full historical backfill, while
    checkpointed collections continue to use `store-time` plus a 30-day overlap.
5. [x] Integrate the first-run full-backfill behavior into the current sequential production orchestration flow and verify that
    the checkpoint is written after successful historical enumeration.
6. [x] Implement local path building using the year/month collection layout.
7. [x] Implement downloader with temp-file then atomic rename.
8. [x] Implement SHA-256 sidecar writing.
9. [x] Implement durable local manifest updates for download and fixity outcomes.
10. Implement spreadsheet write/update behavior.
   - first slice: validate required reporting columns up front and write collection-level start/final status updates from the existing sequential flow
   - later slice: add mid-download progress reporting and move sheet writes behind the dedicated sheet-updater task
11. Implement the `Trio` flow:
   - main orchestrator
   - download worker 1
   - download worker 2
   - sheet updater
12. Add lock and cron wrapper.
13. Run on a small set of collections before scaling up.

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
