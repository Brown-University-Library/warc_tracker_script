# Plan: guarantee retries for failed downloads

USER-UPDATE: I want to go with Option 2, listed below, so I've removed Options 1 and 3.

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

---
