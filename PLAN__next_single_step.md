# Next Single Step: Spreadsheet Write/Update Behavior

## Context for Future Agents

**Code-directives**: review `warc_tracker_script/AGENTS.md` before editing code.

**Master plan reference**: `warc_tracker_script/PLAN__simplified_warc_backup_script.md`

**User preference**: build functionality sequentially from `warc_tracker_script/main.py` when possible, while keeping `main.py` thin and orchestration-focused.

**Current implementation status**:

- `main.py` remains a thin entry point that loads config, configures logging, opens an authenticated `httpx.Client`, and iterates collection jobs.
- `lib/orchestration.py` processes collections sequentially.
- `lib/collection_sheet.py` loads active collection jobs from the spreadsheet.
- `lib/local_state.py` loads and saves `state.json` atomically and now records durable per-file download/fixity outcomes.
- `lib/wasapi_discovery.py` performs production WASAPI discovery with overlap-window checkpoint logic.
- `lib/storage_layout.py` derives year/month partitions from WARC filenames and computes planned WARC/fixity destinations.
- `lib/downloader.py` streams WARC files, writes to `*.partial`, removes stale partial files on retry, and atomically renames successful downloads into place.
- `lib/fixity.py` computes SHA-256 and writes `.sha256` and `.json` sidecars for successfully downloaded WARCs.
- The production flow now reaches local download, fixity creation, and durable manifest/state updates, but it still does not write collection-level progress or summary updates back to the spreadsheet.

---
## Goal of This Step

Implement the first production version of **spreadsheet write/update behavior** so the script can report collection progress and completion status back to the tracking sheet while keeping the local filesystem state as the source of truth.

This step should add a small sheet-update layer that can:

- write an in-progress marker when a collection starts processing
- write a final collection summary when processing finishes
- update a small set of collection-level sheet fields if they are present
- keep spreadsheet logic out of `main.py`
- keep the implementation sequential for now

This step should **not** yet implement Trio concurrency or the separate async sheet-updater task.

---
## Why This Is the Right Next Step

1. **It directly follows the updated implementation sequence**
   - Discovery is done.
   - Path planning is done.
   - Downloading is done.
   - Fixity generation is done.
   - Durable manifest/state recording is done.
   - The next missing production behavior is spreadsheet reporting.

2. **It matches the master plan’s intended control/reporting surface**
   - The spreadsheet is meant to show start, progress, and summary information.
   - Local state already holds the correctness data needed to compute summary writes.

3. **It fits the existing thin-`main.py` sequential flow**
   - `main.py` can remain orchestration-only.
   - `lib/orchestration.py` can call a small sheet-update helper layer at clear checkpoints.

4. **It preserves a small implementation increment**
   - Spreadsheet behavior can be validated before introducing Trio workers or a separate sheet-updater task.

---
## In-Scope Deliverables

Update the sheet-integration layer and orchestration flow so the current sequential production path can, for each processed collection:

- identify the target collection row using existing collection-job data
- write an **In Progress** marker when collection processing begins
- write a final summary update when collection processing finishes
- clear the in-progress marker at the end
- write a small set of collection-level fields when the corresponding columns are present

Likely fields to support first:

- `Server File path- collection level`
- `Last WASAPI fetch`
- `File Count ?`
- `Total Size`
- `In Progress marker`

And add focused tests, likely in:

- `warc_tracker_script/tests/test_collection_sheet.py`
- `warc_tracker_script/tests/test_orchestration.py`

---
## Out of Scope for This Step

- No Trio concurrency.
- No separate async sheet-updater worker.
- No redesign of `main.py`.
- No per-file sheet writes.
- No remote checksum comparison.

---
## Required Behavior from the Master Plan

### When to write

For each collection, the implementation should support:

1. writing an **In Progress** marker when processing begins
2. writing a final summary update when processing finishes
3. clearing the in-progress marker at the end

For this step, it is acceptable to defer mid-download progress batching and implement only start/final writes in the current sequential flow.

### What to write

At collection level, update only a small set of fields if they are present:

- `Server File path- collection level`
- `Last WASAPI fetch`
- `File Count ?`
- `Total Size`
- `In Progress marker`

The implementation should tolerate missing columns and avoid failing the whole collection just because one expected reporting column is absent.

### Source-of-truth rule

- local filesystem state remains the source of truth
- spreadsheet writes are reporting/control only
- spreadsheet write failures should be logged clearly
- spreadsheet write failures should not erase local files or manifest state

---
## Recommended API Shape

Keep the change small and explicit. Illustrative directions:

```python
def build_collection_summary_update(...) -> dict[str, object]:
    ...


def write_collection_progress_update(... ) -> None:
    ...
```

Exact naming can vary if the interface stays simple and testable.

It is acceptable to add a small helper module under `lib/` for spreadsheet write behavior if that keeps orchestration readable.

---
## Orchestration Integration Requirement

Extend the current sequential flow in `lib/orchestration.py` so that it can:

1. write a start marker before discovery/download work begins
2. process the collection through the existing sequential flow
3. compute a collection-level summary from the run results and local paths
4. write a final collection summary at the end
5. clear the in-progress marker before returning
6. preserve the existing thin `main.py` approach

Do this without introducing Trio worker structure yet.

---
## Test Requirements

Add focused `unittest` coverage.

### Minimum tests to include

- **Start marker write**
  - collection processing triggers an in-progress update

- **Final summary write**
  - successful collection processing writes the expected collection-level summary payload

- **Missing-column tolerance**
  - absent optional sheet columns do not crash the reporting flow

- **Spreadsheet write failure handling**
  - write failures are surfaced clearly without breaking local manifest/file state behavior unless explicitly intended

- **Orchestration integration**
  - sequential collection processing invokes the sheet update layer at start and finish

Keep tests local and mocked where appropriate; do not add live network or live Google Sheets tests.

---
## Suggested Implementation Notes

- Keep `main.py` thin.
- Prefer small helper functions in `lib/collection_sheet.py` or a nearby `lib/` helper module rather than embedding sheet-write logic inline.
- Reuse existing collection row metadata from sheet ingestion rather than re-discovering rows in an ad hoc way.
- Keep write payloads explicit and small.
- Match repository style from `AGENTS.md` and `ruff.toml`.
- Log spreadsheet write failures clearly, but keep local-state durability separate.

---
## Success Criteria

- [ ] collection processing writes an in-progress marker to the spreadsheet
- [ ] collection processing writes a final summary update to the spreadsheet
- [ ] the in-progress marker is cleared at the end of processing
- [ ] the implementation tolerates missing optional sheet columns
- [ ] focused `unittest` coverage exists for the new write/update behavior

---
## Likely Follow-Up After This Step

After spreadsheet write/update behavior is implemented, the next step should likely be:

1. implement the `Trio` flow with two download workers plus a separate sheet updater
2. then add lock/cron hardening

---
## Handoff Notes for the Next Agent / New Session

If you are picking this up in a new session, re-read:

- `warc_tracker_script/AGENTS.md`
- `warc_tracker_script/PLAN__simplified_warc_backup_script.md`
- `warc_tracker_script/PLAN__next_single_step.md`

Quick mental model of the codebase right now:

- `main.py` is a thin entry point and should stay that way.
- `lib/orchestration.py` is the current sequential production flow.
- `lib/local_state.py` now persists per-file manifest outcomes durably.
- `lib/collection_sheet.py` already handles sheet ingestion and is the most likely home for small reporting/write helpers unless a separate `lib/` helper proves cleaner.
- The immediate objective is to add the smallest correct spreadsheet update layer that plugs into the existing sequential orchestration flow and reports collection-level start/final status without introducing async structure yet.
