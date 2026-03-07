# Next Single Step: Sequential Spreadsheet Reporting Contract

## Context for Future Agents

**Code-directives**: review `warc_tracker_script/AGENTS.md` before editing code.

**Master plan reference**: `warc_tracker_script/PLAN__simplified_warc_backup_script.md`

**User preference**: build functionality sequentially from `warc_tracker_script/main.py` when possible, while keeping `main.py` thin and orchestration-focused.

**Current implementation status**:

- completed: env/config loading, logging, sheet ingestion, local `state.json`, WASAPI discovery, storage layout, downloader, fixity generation, durable manifest updates, and the sequential production orchestration flow in `main.py` plus `lib/orchestration.py`
- not yet implemented: spreadsheet write/update behavior, Trio concurrency with two download workers plus a separate sheet updater, and lock/cron hardening

---

## Goal of This Step

Implement the first production-ready spreadsheet reporting slice in the existing sequential flow:

1. validate the required reporting columns before significant processing begins
2. write collection-level start status when a collection begins processing
3. write collection-level final status plus summary fields when processing completes

This is the best next step because it establishes the worksheet contract and write API that later progress updates and the async sheet-updater can reuse.

---

## Why This Is the Right Next Step

1. **It is the next unfinished item in the master plan**
   - download, fixity, state, and sequential orchestration are already present

2. **It keeps the architecture clean**
   - `main.py` stays thin
   - substantive spreadsheet logic belongs in `lib/`

3. **It de-risks later Trio work**
   - the queue/task design will be much easier once the status vocabulary and sheet-write contract already exist

4. **It matches the plan's required validation behavior**
   - required reporting fields should fail early before expensive discovery and download work starts

---

## Specific Deliverable

Extend the current sequential production flow so that it validates the presence of these worksheet columns before meaningful processing starts:

- `processing_status_main`
- `processing_status_detail`
- `summary_status_last_wasapi_check`
- `summary_status_downloaded_warcs_count`
- `summary_status_downloaded`
- `summary_status_server_path`

Then, for each processed collection row:

- write a start status such as `discovery-in-progress`
- write a final outcome status
- write the required summary fields from the sequential run result

Keep the spreadsheet as reporting/control only. Local files and `state.json` remain the source of truth.

---

## Recommended Statuses for This Step

Use the bounded `processing_status_main` vocabulary already defined in the master plan.

Minimum statuses needed now:

- `discovery-in-progress`
- `download-planning-complete` or `no-new-files-to-download`
- `downloaded-without-errors`
- `completed-with-some-file-failures`
- `discovery-failed`
- `spreadsheet-update-failed`

`processing_status_detail` should remain short and operator-readable.

---

## Suggested Code Shape

- add reporting-column validation and row-update helpers in `lib/collection_sheet.py` or a small neighboring `lib/` module
- keep `main.py` orchestration-only
- call the reporting helpers from `lib/orchestration.py`
  - once before collection processing begins
  - once when a collection starts
  - once when a collection finishes or fails

Reuse existing `CollectionJob.row_number` metadata rather than introducing a second collection-row lookup path.

---

## Minimum Test Coverage

Add focused `unittest` coverage for:

- required reporting-column validation failing clearly when a column is missing
- start-status writes using the expected row and payload
- final successful status plus summary writes
- failure-path final statuses for discovery failure and file-failure outcomes
- sheet-write failures surfacing clearly without corrupting local manifest or downloaded-file state

Likely test files:

- `warc_tracker_script/tests/test_collection_sheet.py`
- `warc_tracker_script/tests/test_orchestration.py`

---

## Out of Scope for This Step

- Trio concurrency
- dedicated async sheet-updater task
- mid-download progress milestones such as `20%`, `40%`, `60%`, and `80%`
- lock/cron wrapper work
- redesigning the existing sequential downloader/fixity flow

---

## Success Criteria

- [ ] required reporting columns are validated before significant processing begins
- [ ] sequential collection processing writes a start status to the spreadsheet
- [ ] sequential collection processing writes a final status plus the required summary fields
- [ ] sheet-write failures are logged and surfaced without undoing durable local state
- [ ] focused `unittest` coverage exists for validation and start/final reporting behavior

---

## Likely Follow-Up After This Step

1. add mid-download progress reporting and/or move sheet writes behind the dedicated sheet-updater task
2. implement the full Trio flow with two dedicated download workers and one sheet updater
3. add lock and cron wrapper hardening

---

## Handoff Notes

If you pick this up in a new session, re-read:

- `warc_tracker_script/AGENTS.md`
- `warc_tracker_script/PLAN__simplified_warc_backup_script.md`
- `warc_tracker_script/PLAN__next_single_step.md`

Quick mental model:

- `main.py` should stay thin
- `lib/orchestration.py` is the current production spine
- the best next implementation target is still the spreadsheet reporting contract in the sequential flow
- once that exists, async progress batching becomes a smaller follow-up instead of a combined architecture-and-contract change

