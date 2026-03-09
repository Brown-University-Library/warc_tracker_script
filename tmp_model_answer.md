# Investigation summary

I reviewed:
- `warc_tracker_script/AGENTS.md`
- `warc_tracker_script/PLAN__simplified_warc_backup_script.md`
- `logs/warc_tracker_script.log`
- the relevant orchestration/status code in `warc_tracker_script/lib/orchestration.py`

## Short answer

I do **not** think this is a literal arithmetic off-by-1 bug.

I think it is a **count-definition mismatch**:
- the second-run in-progress denominator (`7`) is the number of **planned downloads**
- the second-run final success count (`6`) is the number of **actual successful download operations**
- one of the 7 planned items was already present on disk by the time the second run reached the download loop, so it was **planned** but then **skipped**, which is why the final text said `6`

## What the log shows

### First run

The first run clearly planned 24 downloads:
- `Collection 22900 has 24 reconciliation candidates, 1 discovery candidates, and 24 merged planned downloads.`
- `Collection 22900 spreadsheet status updated: download planning complete with 24 files planned.`
- `Collection 22900 spreadsheet status updated: downloading in progress for 24 planned files.`

That matches your understanding that the collection really had 24 files.

The first run ended with 6 failures:
- `Collection 22900 has 1 pending candidates, 24 planned downloads, 18 download successes, 6 download failures, 0 skipped existing files, 18 fixity successes, and 0 fixity failures.`

So after run 1, there were 18 successfully downloaded files on disk and 6 retryable missing files.

### Second run

The second run shows exactly why `7` appeared:
- `Collection 22900 has 6 reconciliation candidates, 1 discovery candidates, and 7 merged planned downloads.`

So the spreadsheet showed `7` because the code uses the merged planned-download list length for in-progress reporting.

Later in the same run, the log shows this:
- `Collection 22900 skipping download for ARCHIVEIT-22900-QUARTERLY-JOB2649176-0-SEED3256845-20260105141018582-00000-aokwrf4m.warc.gz because the destination already exists`

And then the final summary says:
- `Collection 22900 has 0 pending candidates, 7 planned downloads, 6 download successes, 0 download failures, 1 skipped existing files, 6 fixity successes, and 0 fixity failures.`

That is the direct explanation for the visible mismatch:
- `7 planned`
- `6 successful downloads`
- `1 skipped existing file`

## Why that happened in code

The relevant code paths are in `warc_tracker_script/lib/orchestration.py`.

### In-progress denominator uses planned-download count

`process_collection_job()` writes the download-start spreadsheet status using:
- `write_collection_download_start_status(..., len(planned_downloads))`

And `build_download_start_status()` formats that as:
- `0% (0/{total_planned_downloads} files)`

So the second run's initial denominator of `7` came from `len(planned_downloads)`.

### Discovery planning currently includes a rediscovered file even if it already exists locally

`build_planned_downloads()` creates planned download items from discovered WASAPI records if they have:
- a usable filename
- a usable source URL

It does **not** check whether the destination WARC already exists locally.

That means the rediscovered quarterly file was included in `planned_downloads`, contributing to the `7`.

### Actual download results exclude skipped-existing items

In `run_planned_downloads()`:
- if `destination_path.exists()`, the code logs a skip and `continue`s immediately
- it does **not** append a `DownloadResult` for that skipped item

So skipped-existing items:
- still count in `planned_downloads`
- do **not** count in `download_results`

### Final success text uses only actual successful downloads

`build_collection_final_report()` computes:
- `successful_download_count = sum(1 for result in download_results if result.success)`
- status detail: `'{successful_download_count} file downloads completed successfully'`

So the final `6` is the number of actual successful download operations during that run, not the number of planned items.

## Conclusion

Your observed `7` then `6` sequence is explained by current code and log evidence.

It is **not** that the collection suddenly had 7 missing files.

Instead:
- there were really **6 retry candidates** left from the first run
- plus **1 rediscovered WASAPI record**
- that rediscovered file was already present locally
- so it was counted during planning, but skipped during execution
- therefore the final success message reported only `6`

## Is this a bug?

I would call it a **real reporting bug / UX inconsistency**, though not a literal off-by-1 arithmetic error.

The user-visible issue is that the spreadsheet mixes two different notions of count:
- **planned items** during in-progress reporting
- **actual successful download operations** in the final success text

That mismatch is what made the second run look suspicious.

## Smallest likely fix direction

The cleanest fix is probably to make the in-progress denominator reflect **actual work that still needs download**, not raw merged planned entries.

In practice, that likely means filtering discovery-based planned downloads so they do not enter the active planned list when the destination WARC already exists locally.

An alternative would be to keep the current planning behavior but change the final wording so it explicitly distinguishes:
- planned items
- skipped-existing items
- successful new downloads

But based on the current spreadsheet wording, I think the stronger fix is to make the progress denominator align with actual download work.

## Bottom line

- The collection total of `24` appears correct.
- The second-run `7` came from `6 reconciliation retries + 1 rediscovered WASAPI item`.
- The second-run final `6` came from `6 actual successful downloads`, with `1 skipped existing file`.
- So this looks like a **planned-vs-executed counting mismatch**, not a true arithmetic off-by-1.