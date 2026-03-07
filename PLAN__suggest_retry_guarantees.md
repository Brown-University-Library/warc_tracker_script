# Plan: guarantee retries for failed downloads

## Context

Goal: guarantee that files with prior download failures are retried in a future run.

Relevant current behavior observed in the code and local data:

- `run_planned_downloads()` skips a file only when the planned destination WARC already exists on disk.
- The skip decision is based on `Path.exists()`, not on `state.json`.
- Collection `22900` currently has `16` local WARC files on disk and `8` `state.json` entries with `download_status: failed`.
- Current retry behavior is indirect: a failed file is retried only if a future WASAPI discovery run returns that record again.
- Incremental discovery is based on `enumeration_checkpoint_store_time_max - 30 days`.

This means the current implementation does not provide a hard guarantee that failed files will always be retried in a later run. It provides a likely retry path only while those files continue to reappear in the overlap window.

## Requirement

The desired behavior is stronger than the current implementation:

- if a file is recorded as failed in `state.json`
- and the local WARC file is still absent
- then a future run should retry it regardless of whether WASAPI rediscovery still happens to include it

## Option 1: explicit retry queue from `state.json` failed entries

## Summary

Use `state.json` as a durable retry queue for failed files.

## Behavior

At the start of each collection run:

1. load `state.json`
2. scan `files` for entries where:
   - `download_status == 'failed'`
   - `warc_path` does not exist on disk
   - `source_url` is present
3. create retry download candidates from those entries
4. merge those retry candidates with any newly discovered WASAPI candidates
5. deduplicate by filename
6. attempt all merged candidates in the run

## Advantages

- strongest guarantee relative to the requirement
- works even after a file has aged out of the 30-day overlap window
- keeps retry intent in the same durable local state already used by the collection
- smallest conceptual gap from the current data model, because failed entries already store `source_url`, `warc_path`, and error history

## Risks / costs

- requires careful merge/deduplication with normal discovery results
- should avoid infinite hot-loop retrying of permanently broken URLs in a single run
- may need a simple retry-throttling rule later, such as `last_attempt_at` backoff, but that is optional for a first slice

## Implementation shape

The smallest version would:

- add a helper that builds retry candidates from failed manifest entries
- merge them into `planned_downloads`
- preserve current filesystem `exists()` skip logic

This is the cleanest path to a real guarantee.

## Option 2: filesystem reconciliation against all manifest entries

## Summary

Treat `state.json` as a desired-manifest and the filesystem as actual presence, then retry any manifest entry whose WARC path is missing.

## Behavior

At the start of each run:

1. load all manifest entries in `state.json`
2. for each entry with a usable `warc_path` and `source_url`, check whether the WARC exists on disk
3. if the file is missing and the manifest does not say `downloaded` with a confirmed local file, queue it for download
4. merge those queued items with fresh WASAPI discoveries

## Advantages

- also provides a strong guarantee for missing files
- not limited to `download_status: failed`
- can recover from partial/manual filesystem loss, not just HTTP failures

## Risks / costs

- broader than the immediate problem, so it is a more opinionated behavioral shift
- can requeue items for reasons unrelated to transient failures, which may or may not be desired
- needs extra care around entries that say `downloaded` but whose local file was later removed or moved

## Implementation shape

This is similar to Option 1, but broader:

- scan all manifest entries
- verify `warc_path` existence on disk
- queue any missing local WARC with a usable `source_url`

This is powerful, but it reaches beyond "guarantee retries for failed downloads" into "guarantee reconciliation of state vs disk".

## Option 3: keep discovery-driven flow, but pin failed filenames into forced rediscovery/retry logic

## Summary

Keep WASAPI discovery as the main driver, but add explicit retry handling for failed files discovered in prior runs.

## Behavior

A few possible variants fit this family:

- widen the overlap window for collections with failures
- trigger a periodic full backfill when failed entries exist
- maintain a list of failed filenames and only retry them when rediscovered again

## Advantages

- preserves the current discovery-first architecture
- smaller conceptual change to the orchestration flow
- may require fewer new helper structures than an explicit retry queue

## Risks / costs

- weakest guarantee of the three options
- still depends partly or wholly on remote rediscovery behavior
- a larger overlap window or periodic full backfill increases remote enumeration cost without truly guaranteeing that a specific failed file will reappear
- if the remote API stops returning an older failed record, the retry guarantee is lost

## Implementation shape

This option can improve retry likelihood, but not give the guarantee you asked for unless it eventually collapses into Option 1 or 2.

## Recommendation

Recommend **Option 1: explicit retry queue from `state.json` failed entries**.

## Why Option 1 is the best fit

- It directly matches the requirement: guarantee retries for files already known to have failed.
- It uses data the system already persists today:
  - filename
  - source URL
  - target WARC path
  - attempt history
- It does not require broad reinterpretation of the manifest.
- It avoids relying on future WASAPI rediscovery windows.
- It is a smaller, clearer change than full manifest-to-filesystem reconciliation.

## Why not Option 2 first

Option 2 is attractive and may be worth doing later, but it expands the problem from:

- retry known failures

to:

- reconcile all manifest/disk mismatches

That is a larger policy choice.

## Why not Option 3 first

Option 3 does not truly satisfy the requested guarantee. It can improve odds, but not provide certainty.

## Recommended minimum implementation slice

Implement the smallest version of Option 1:

1. add a helper that reads failed entries from `state.json`
2. keep only entries whose `warc_path` is absent on disk and whose `source_url` is usable
3. convert them into `PlannedDownload` objects
4. merge them with discovery-based `planned_downloads`
5. deduplicate by filename
6. run the existing sequential download loop unchanged

## Nice follow-up improvements after that

- add a small retry-backoff rule based on `last_attempt_at`
- log counts for:
  - retry candidates from state
  - discovery candidates from WASAPI
  - merged total after deduplication
- optionally mark a manifest field such as `retry_queued_at`

## Bottom line

If you want a real guarantee that failed files will be retried in a future run, the best approach is:

- persist failed download entries in `state.json`
- treat those failed entries as an explicit retry queue on later runs
- still confirm actual local presence from the filesystem before retrying

That gives a direct and durable guarantee without depending on overlap-window rediscovery.
