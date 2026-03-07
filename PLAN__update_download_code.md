# Plan: update download code

## Context reviewed

Reviewed inputs:

- `AGENTS.md`
- `PLAN__simplified_warc_backup_script.md`
- `logs/warc_tracker_script.log`
- `warc_downloads/collections/22900/state.json`
- current sequential download/discovery code in `lib/orchestration.py`, `lib/local_state.py`, `lib/downloader.py`, and `lib/wasapi_discovery.py`

## Observed facts

- The WASAPI discovery log for collection `22900` shows `24` discovered file records on page `1`.
- The sequential orchestration built `24` planned download paths and `24` planned downloads.
- The same log shows the run continued for roughly `21` minutes after discovery.
- The run summary at the end says:
  - `24` pending candidates
  - `24` planned downloads
  - `16` download successes
  - `8` download failures
  - `16` fixity successes
- The current `state.json` for collection `22900` contains `24` file entries total:
  - `16` downloaded
  - `8` failed
- The failure pattern in the log is dominated by upstream `502 Bad Gateway` responses coming from redirected `archive.org` URLs.

## Primary hypothesis: what most likely went wrong

The most likely explanation for the earlier discrepancy of "`24` discovered" versus "only `9` entries in `state.json`" is that the file was inspected while the long sequential run was still in progress, not after it had finished.

Why this is the strongest explanation:

- The code writes `state.json` incrementally after each file attempt.
- The log contains repeated `Saved collection 22900 state after processing ...` messages throughout the run.
- The run started processing downloads at `13:19:58` and did not finish until `13:40:41`.
- Several of the later successful entries in `state.json` have timestamps around `18:39` and `18:40` UTC, which correspond to the end of the run.
- The current `state.json` now reflects all `24` discovered files, which matches the completed log summary.

So the earlier "9 entries" snapshot was probably a mid-run snapshot rather than evidence that the code permanently dropped 15 records.

## Secondary hypotheses: real weaknesses in the current code

Even though the specific mismatch was probably caused by checking the state file mid-run, the current implementation still has some real weaknesses that can make this confusing or operationally risky.

### 1. Checkpoint advances before download work finishes

Current behavior:

- `process_collection_job()` saves `enumeration_checkpoint_store_time_max` immediately after discovery succeeds.
- This happens before any of the `24` downloads are attempted.

Why this is risky:

- If the process crashes after discovery but before most downloads are attempted, the checkpoint has already advanced.
- The overlap-window design should eventually recover many missed files, but recovery becomes dependent on the overlap logic instead of the state file giving a complete picture of what discovery found in this run.
- During a first-run full backfill, this is especially awkward because the state file can temporarily show a fresh checkpoint but only partial file-manifest coverage.

### 2. Discovered-but-not-yet-attempted files are not durably recorded up front

Current behavior:

- The manifest only gets a file entry after a download attempt occurs.
- A discovered record that has not yet been attempted has no representation in `state.json`.

Why this matters:

- Mid-run inspection makes it look as if discovery found fewer files than it actually did.
- If the process stops partway through, the state file does not distinguish between:
  - not discovered
  - discovered but not yet attempted
  - attempted and failed
- This makes debugging and restart reasoning harder.

### 3. Logging shows detailed per-file planning, but state does not expose discovery/planning progress

Current behavior:

- The log clearly shows all `24` planned files.
- The persisted state does not have a discovery-run summary such as `discovered_count`, `planned_download_count`, or `remaining_count`.

Why this matters:

- Operators comparing the log against `state.json` can infer a false persistence bug.
- The system lacks a durable bridge between discovery and execution.

### 4. Upstream download failures are redirected `502`s and may need stronger retry handling

Current behavior:

- Many failures are `502 Bad Gateway` responses against redirected `archive.org` hosts.
- `download_to_path()` performs one streaming attempt and returns failure immediately.

Why this matters:

- Some failures are probably transient and recoverable within the same run.
- The current design pushes all retry behavior to later reruns instead of applying bounded in-run retries for obvious transient server failures.

## Recommended code changes

## Recommendation 1: persist discovered/planned files to state before downloads begin

Add a planning-state write immediately after discovery and planned-download construction.

Suggested behavior:

- For every discovered record with a usable filename, create or update a manifest entry before download begins.
- Record a lightweight status such as:
  - `status: discovered`
  - or `status: pending_download`
- Also record stable metadata when available:
  - `source_url`
  - `warc_path`
  - optional `discovered_at`
  - optional `store_time`

Expected benefit:

- `state.json` will reflect all discovered files early in the run.
- A mid-run inspection will no longer look like silent data loss.
- Crash recovery and debugging become much easier.

## Recommendation 2: persist collection-level run metadata for discovery and planning

Add a small top-level collection-run summary block in `state.json`.

Suggested fields:

- `last_discovery_completed_at`
- `last_discovery_record_count`
- `last_planned_download_count`
- `last_run_status`

Optional first-pass fields only:

- `last_run_status: discovery-complete`
- `last_run_status: downloads-in-progress`
- `last_run_status: downloads-complete`

Expected benefit:

- Makes it immediately clear that discovery found `24` files even if only part of the download loop has finished.
- Provides durable operational context without relying on the log file alone.

## Recommendation 3: consider moving checkpoint persistence until after planning-state persistence

At minimum, change the order so that:

1. discovery succeeds
2. discovered/planned files are durably written to `state.json`
3. checkpoint is written
4. downloads begin

Why this ordering is better:

- If a crash happens after checkpoint advancement, the state file will still contain the full discovered set for that run.
- This preserves the current design decision that download failures do not block checkpoint advancement, while avoiding the weaker state shape that exists today.

## Recommendation 4: add bounded retries for transient `5xx` download failures

Enhance `download_to_path()` or a small orchestrator wrapper around it to retry transient download failures.

Suggested first slice:

- retry a small number of times for `502`, `503`, `504`, and connection-reset style transport errors
- use short exponential backoff
- keep deleting stale `.partial` files before each retry
- include retry-attempt logging with filename and URL

Expected benefit:

- Reduces the number of failures caused by temporary upstream instability.
- Especially useful because the failures observed here appear to be transient redirected-host failures, not permanent `404`-style misses.

## Recommendation 5: make "skipped because file exists" update the manifest if needed

Current behavior:

- If a destination WARC already exists, the code logs and `continue`s.
- It does not ensure the manifest entry is updated for that file in the same branch.

Suggested change:

- When skipping because the WARC already exists, ensure the manifest entry is present and consistent.
- If fixity sidecars already exist, mark them too.
- If fixity sidecars do not exist, either queue fixity creation or mark the file as needing fixity.

Expected benefit:

- Keeps filesystem truth and manifest truth aligned.
- Prevents under-reporting in `state.json` for reruns.

## Recommendation 6: improve final reporting terminology

The current final report counts only attempted downloads in some places, while the state file is becoming the broader source of truth.

Suggested changes:
 
- distinguish clearly between:
  - discovered files
  - planned downloads
  - attempted downloads
  - successful downloads
  - failed downloads
- include these counts in logging and, if useful, future spreadsheet reporting

Expected benefit:

- Prevents confusion like the one seen here.
- Makes the distinction between discovery and execution explicit.

## Minimum recommended implementation slice

If you want the smallest high-value change first, implement these in order:

1. Write manifest entries for all discovered/planned files before downloads start.
2. Save a small top-level discovery/planning summary to `state.json`.
3. Move checkpoint persistence until after that state write.
4. Add bounded retries for transient `5xx` download failures.

## Bottom line

The evidence does not currently support a bug where `15` discovered files were permanently omitted from `state.json`.

Instead, the most likely cause is:

- the state file was examined while the sequential download run was still in progress
- combined with a real design limitation: discovered files are not written to `state.json` until each individual download attempt happens

So the core improvement is not "fix missing persistence after download" but rather:

- persist discovery/planning state earlier and more explicitly
- then make transient download failures more resilient
