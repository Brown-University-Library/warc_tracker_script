# Plan: update download code

## Context reviewed

Reviewed inputs:

- `AGENTS.md`
- `PLAN__simplified_warc_backup_script.md`
- current code in `main.py`, `lib/orchestration.py`, `lib/local_state.py`, and `lib/downloader.py`
- current tests in `tests/test_downloader.py` and `tests/test_orchestration.py`

## Current-state assessment

This plan was written against an earlier version of the download flow. Some suggestions are still useful, but others have been partly or fully superseded by later code changes.

### What has changed since the earlier draft

- The production flow still runs sequentially, but it now includes spreadsheet start/final reporting from `lib/orchestration.py`.
- The production flow now includes reconciliation-driven retry planning via `build_reconciliation_retry_downloads()` and `merge_planned_downloads()`.
- The local manifest is updated durably after each attempted download and after each successful download's fixity work.
- The downloader still performs exactly one streaming attempt per file and deletes stale `*.partial` files before the attempt.

### What remains true from the earlier draft

- `process_collection_job()` still advances `enumeration_checkpoint_store_time_max` immediately after successful discovery and before download attempts begin.
- Discovered files are still not written to `state.json` until each individual download attempt occurs.
- If a planned destination WARC already exists, `run_planned_downloads()` logs and skips it without ensuring that the manifest and fixity metadata are brought into alignment.
- Final logging still mixes several concepts together; it reports `pending candidates`, `planned downloads`, `download successes`, `download failures`, and `skipped existing files`, but it does not durably persist a discovery/planning summary.
- `download_to_path()` still has no bounded in-run retry behavior for transient upstream `5xx` or transport errors.

## Recommendation review

### Recommendation 1: persist discovered/planned files to state before downloads begin

Status: **still applicable and still high-value**.

Why it still matters:

- The current manifest only becomes complete as the sequential loop progresses.
- Mid-run inspection still cannot distinguish between `not discovered yet` and `discovered but not attempted yet`.
- Crash recovery reasoning would be clearer if discovery/planning state were durably recorded before the first download begins.

Suggested revision:

- After discovery and planned-download construction, create or update manifest entries for every planned filename before calling `run_planned_downloads()`.
- Record stable metadata when available:
  - `source_url`
  - `warc_path`
  - optional `store_time`
  - optional planning/discovery timestamp
- Use an explicit pre-download state such as `pending_download` rather than overloading `failed` or `downloaded`.

### Recommendation 2: persist collection-level run metadata for discovery and planning

Status: **still applicable**, but should stay lightweight.

Why it still matters:

- The current code logs discovery/planning counts but does not save them durably.
- A small top-level summary block would make state inspection much easier during long runs and after interruptions.

Suggested fields:

- `last_discovery_completed_at`
- `last_discovery_record_count`
- `last_discovery_planned_download_count`
- `last_download_loop_attempted_count`
- `last_run_status`

Keep this small and operational; do not turn `state.json` into a second event log.

### Recommendation 3: move checkpoint persistence until after planning-state persistence

Status: **still applicable**.

This is the key ordering improvement if recommendation 1 is implemented.

Preferred order:

1. discovery succeeds
2. planned/discovered manifest state is written durably
3. checkpoint is written
4. downloads begin

Reasoning:

- The current design choice that download failures do not block checkpoint advancement can still stand.
- But if checkpoint advancement remains earlier than any durable planning-state write, the state file still gives a weaker picture after an interruption.

### Recommendation 4: add bounded retries for transient `5xx` download failures

Status: **still applicable and probably the most useful download-layer change**.

Current code facts:

- `download_to_path()` performs a single `client.stream('GET', source_url)` attempt.
- It removes stale partials before the attempt and cleans up partials after failure.
- It returns a structured `DownloadResult`, which makes it straightforward to wrap with retry logic.

Recommended first slice:

- Retry a small fixed number of times for clearly transient failures such as `502`, `503`, `504`, and selected `httpx` transport exceptions.
- Keep retry logic outside the lowest-level byte-stream loop if that keeps the code simpler.
- Log retry count, filename, and source URL clearly.
- Continue deleting stale partial files before each attempt.

### Recommendation 5: make `destination already exists` reconcile manifest/fixity state

Status: **still applicable and now more important**.

Why it matters more now:

- The codebase has added reconciliation-driven retry planning, but the `destination_path.exists()` branch still just logs and skips.
- That means an on-disk WARC can continue to coexist with missing or stale manifest/fixity metadata.
- This weakens the local-state model that the broader project plan treats as the main durable operational record.

Recommended behavior:

- When a WARC already exists, ensure the manifest entry exists and points at the correct `warc_path` and `source_url`.
- If fixity sidecars exist, record them.
- If fixity sidecars do not exist, either generate them immediately or mark the manifest entry as needing fixity reconciliation.

### Recommendation 6: improve final reporting terminology

Status: **still applicable, but wording should be updated to match the current code**.

The current code already distinguishes some counts in logging, so the need is no longer "add all reporting" but rather "make the count vocabulary more explicit and consistent across logs, state, and future spreadsheet reporting."

Recommended count vocabulary:

- `discovered_record_count`
- `planned_download_count`
- `attempted_download_count`
- `successful_download_count`
- `failed_download_count`
- `skipped_existing_count`
- `fixity_success_count`
- `fixity_failure_count`

## Additional observations not emphasized enough in the earlier draft

### Spreadsheet progress reporting is no longer entirely missing

The earlier draft treated spreadsheet updates as absent. That is now outdated.

Current state:

- collection start status is written before discovery
- final collection reporting is written at the end
- mid-download progress updates are still not implemented

So future work should describe this accurately as **expanding** spreadsheet reporting, not **introducing it from zero**.

### Reconciliation retries reduce the urgency of some older concerns, but do not eliminate them

The newer reconciliation logic helps recover from some mismatch cases by retrying manifest-recorded files whose `warc_path` is missing on disk.

However, it does **not** solve the earlier-planning visibility gap, because files that were discovered but never written to the manifest still do not participate in that reconciliation path.

## Revised priority order

If you want the smallest high-value implementation sequence now, do this:

1. Persist planned/discovered manifest entries before downloads begin.
2. Write a compact top-level discovery/planning summary into `state.json`.
3. Move checkpoint persistence to after that durable planning-state save.
4. Reconcile the `destination already exists` branch so manifest and fixity state stay aligned.
5. Add bounded retries for transient download failures.
6. Tighten logging/reporting terminology so discovery, planning, attempt, skip, download, and fixity counts are explicit.

## Bottom line

The older plan's central insight is still valid: the biggest remaining weakness is the gap between discovery/planning and durable local-state visibility.

But the plan needed revision because the codebase has moved forward:

- spreadsheet start/final reporting now exists
- reconciliation-driven retry planning now exists
- incremental per-file manifest persistence now exists

So the remaining work is narrower than the earlier draft implied:

- persist planning state earlier
- align `already exists` handling with manifest/fixity truth
- add bounded transient-failure retries
- make durable and logged counts easier to interpret
