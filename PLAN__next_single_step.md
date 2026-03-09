# Next Single Step: Update Spreadsheet Summary Fields to Collection Totals After Processing

## Context for Future Agents

**Code-directives**: review `warc_tracker_script/AGENTS.md` before editing code.

**Plan reference**:

- `warc_tracker_script/PLAN__simplified_warc_backup_script.md`

**Focus of this step**: after processing finishes for a collection, update the spreadsheet fields `sum--Downloaded-WARCs-Count` and `sum--Downloaded-WARCs-Size` so they reflect the total downloaded WARC count and total downloaded WARC size for that collection, not just the current run's incremental results.

The production code already treats the local filesystem and per-collection `state.json` as the source of truth. This step should keep that design and only adjust how final spreadsheet summary values are computed.

---

## Goal of This Step

Make the final collection-level spreadsheet summary write use collection totals for:

1. `sum--Downloaded-WARCs-Count`
2. `sum--Downloaded-WARCs-Size`

For a processed collection, those values should represent the total set of downloaded WARCs currently present for that collection's local backup, regardless of whether the current run downloaded many files, one file, or zero files.

That is the whole feature for this step.

---

## Why This Is the Right Next Step

1. **It matches the source-of-truth design**
   - the master plan says the filesystem and local state are authoritative
   - a final sheet summary should report the current collection total, not just transient run activity

2. **It improves spreadsheet accuracy after no-op or partial runs**
   - if a run downloads nothing new, the summary fields should still show the collection's full backed-up totals
   - if a run downloads only a subset of files, the summary should still describe the full collection-local state after the run ends

3. **It is a small, well-bounded change**
   - this should fit inside the existing sequential orchestration and summary-writing flow
   - it does not require Trio, queueing, or a new storage model

4. **It prepares later reporting work**
   - once these summary fields are based on collection totals, later spreadsheet refinements can assume the summary columns are stable and cumulative

---

## Guiding Constraints from the Project Plan

This step should follow these project rules from `PLAN__simplified_warc_backup_script.md`:

- the local filesystem and `state.json` remain the source of truth
- the spreadsheet is for reporting and control, not correctness
- keep the current sequential orchestration path
- make the smallest correct change
- keep `main.py` thin and orchestration-focused

Interpretation for this step:

- do not compute the final summary values only from the current run's newly planned or newly successful downloads
- do compute them from authoritative local collection state after processing completes
- prefer reusing existing orchestration and sheet-update helpers rather than introducing a new abstraction layer

---

## Specific Implementation Plan

### 1. Review how final summary values are currently assembled

Inspect the current final collection-summary code path and identify:

- where `sum--Downloaded-WARCs-Count` is populated
- where `sum--Downloaded-WARCs-Size` is populated
- whether those values currently come from run-local counters, successful-download counters, manifest entries, or filesystem inspection

Expected outcome of this review:

- identify the exact helper or call site that builds the final spreadsheet summary payload
- confirm whether the current behavior is run-scoped instead of collection-total-scoped
- determine the narrowest place to change the calculation

### 2. Define the authoritative totaling rule for a collection

Use one explicit rule in code for the final summary fields.

Recommended rule:

- `sum--Downloaded-WARCs-Count` = total number of downloaded WARC files currently present for the collection
- `sum--Downloaded-WARCs-Size` = total byte size of those downloaded WARC files currently present for the collection

The implementation should choose one authoritative data source and apply it consistently.

Preferred order of thought:

1. use data already durably tracked in local state if it is complete and trustworthy for current on-disk files
2. otherwise derive totals from the local collection filesystem layout already used by the project

Important design rule:

- do not rely only on files newly discovered or newly downloaded in the current run

### 3. Add or refine one helper that computes collection totals

Implement or adjust a focused helper in the current production layer that returns collection-level totals needed by the final spreadsheet summary.

Recommended helper output:

- total downloaded WARC count
- total downloaded WARC size in bytes

The helper should be designed so the final summary writer can call it once after processing is complete.

Important guardrails:

- keep the helper pure or near-pure when practical
- avoid embedding spreadsheet-writing code inside the totaling helper
- avoid duplicating path traversal logic if storage-layout helpers already exist

### 4. Decide how to treat manifest entries versus on-disk files

Before editing, confirm the correct inclusion rule for totals.

Recommended rule for this step:

- count only WARCs that are actually present on disk and considered successfully downloaded
- do not count failed entries
- do not count planned-only entries
- do not count missing files merely because they still appear in `state.json`

This keeps the final spreadsheet summary aligned with the collection's actual local holdings.

### 5. Update the final spreadsheet summary write to use totals

At the current final collection-summary write point, replace any run-local count/size values with the new total count/size values.

Recommended behavior:

- final summary always writes total downloaded WARC count for the collection
- final summary always writes total downloaded WARC size for the collection
- this happens even when the current run downloads zero new files

This is the key product behavior change for the step.

### 6. Preserve existing status and outcome behavior

Do not redesign the existing collection status flow in this step.

Keep the current behavior for:

- `processing_status_main`
- `processing_status_detail`
- final success/failure outcome handling
- final server-path and last-WASAPI-check reporting

Only change the meaning of the two summary fields so they report collection totals.

### 7. Add logging that makes the totaling basis explicit

Add or adjust log output so it is clear when final collection totals are computed and written.

The logs should make it easy to confirm:

- the collection id being summarized
- the total WARC count used for the sheet write
- the total WARC byte size used for the sheet write
- whether totals came from local state, filesystem inspection, or a combined validated approach

This will make validation easier during cron-style runs.

---

## Likely Code Touch Points

- `warc_tracker_script/lib/orchestration.py`
  - inspect the current final collection-summary assembly
  - replace run-scoped summary metrics with collection-total metrics
- storage/state helpers already used by orchestration
  - only if a small helper addition is the cleanest way to compute totals
- `warc_tracker_script/tests/test_orchestration.py`
  - add focused tests for final summary totals
- any tests covering sheet-summary payload construction
  - extend them if they already exist at a lower layer

Keep `main.py` thin and avoid pushing business logic there.

---

## Minimum Test Coverage

Add focused `unittest` coverage for:

- a collection with existing previously downloaded WARCs and zero new downloads still writes total count and total size to the spreadsheet
- a collection with newly downloaded files writes totals that include both prior and newly added WARCs
- failed or planned-only manifest entries are not counted in the final summary totals
- missing on-disk files are not counted even if stale manifest data exists
- final summary writing still preserves the existing non-total summary/status fields

If current tests already mock the spreadsheet write payload, extend those tests instead of adding a broader integration test unless necessary.

---

## Out of Scope for This Step

- changing progress or in-run status reporting
- changing the display format of the size field
- moving sheet writes behind a dedicated sheet-updater task
- implementing Trio orchestration
- redesigning manifest structure unless a tiny additive change is required
- lock or cron-wrapper hardening

---

## Success Criteria

- [ ] after collection processing completes, `sum--Downloaded-WARCs-Count` reflects the total downloaded WARCs for that collection
- [ ] after collection processing completes, `sum--Downloaded-WARCs-Size` reflects the total downloaded WARC size for that collection
- [ ] totals are not limited to files downloaded in the current run
- [ ] stale failed or planned-only entries are not counted as downloaded totals
- [ ] focused `unittest` coverage exists for no-op, incremental, and stale-manifest edge cases

---

## Likely Follow-Up After This Step

1. decide whether the spreadsheet size field should remain raw bytes or be formatted into a more human-friendly display value
2. review whether any other collection-level summary fields are still run-scoped when they should be total-scoped
3. continue the remaining spreadsheet-update improvements only after the total-summary behavior is stable

---

## Handoff Notes

If you pick this up in a new session, re-read:

- `warc_tracker_script/AGENTS.md`
- `warc_tracker_script/PLAN__simplified_warc_backup_script.md`
- `warc_tracker_script/PLAN__next_single_step.md`

Quick mental model:

- this step is about **changing final spreadsheet summary metrics from run totals to collection totals**
- keep the filesystem and `state.json` as the source of truth
- keep the change small and inside the current sequential orchestration
- do not redesign statuses or jump ahead to Trio
