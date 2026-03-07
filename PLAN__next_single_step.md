# Next Single Step: Spreadsheet Write/Update Behavior

## Context for Future Agents

**Code-directives**: review `warc_tracker_script/AGENTS.md` before editing code.

**Master plan reference**: `warc_tracker_script/PLAN__simplified_warc_backup_script.md`

**User preference**: build functionality sequentially from `warc_tracker_script/main.py` when possible, while keeping `main.py` thin and orchestration-focused.

**Current implementation status from the master plan**:

- completed: env/config loading, logging, sheet ingestion, local `state.json`, WASAPI discovery, storage layout, downloader, fixity generation, durable manifest updates, and the sequential production orchestration flow
- not yet implemented in production: spreadsheet write/update behavior, Trio concurrency with two download workers plus a separate sheet updater, and later lock/cron hardening

---
## Goal of This Step

Implement the **first concrete slice** of spreadsheet reporting in the existing sequential flow:

1. validate the required spreadsheet reporting columns up front
2. write collection-level **start** and **final** status updates
3. keep `main.py` thin and leave Trio work for the following step

This is narrower than “all spreadsheet behavior,” but it is the best next single step because it establishes the spreadsheet contract and the sequential integration points that later progress updates and the async sheet-updater can reuse.

---
## Why This Is the Right Next Step

1. **It follows the implementation sequence exactly**
   - the plan marks spreadsheet behavior as the next unfinished production feature after download/fixity/state work

2. **It aligns with the plan’s stricter spreadsheet contract**
   - the detailed spreadsheet section now says the script should validate required reporting fields early, before significant processing begins

3. **It keeps the change small and architecturaly clean**
   - add the reporting contract and the first start/final writes now
   - defer progress batching and Trio queue/task structure until the reporting interface exists

4. **It matches the repo guidance and user preference**
   - keep `main.py` orchestration-only
   - put substantive sheet-write logic into `lib/`

---
## Specific Deliverable for This Step

Extend the current sequential production flow so that, before meaningful collection processing starts, production code validates the presence of these required worksheet columns:

- `processing_status_main`
- `processing_status_detail`
- `summary_status_last_wasapi_check`
- `summary_status_downloaded_warcs_count`
- `summary_status_downloaded`
- `summary_status_server_path`

Then, for each processed collection in the sequential flow:

- write a **start** status such as `discovery-in-progress`
- write a **final** status/outcome plus summary values when processing ends
- keep the sheet as reporting/control only, with local files and `state.json` remaining the source of truth

This step should explicitly **not** try to implement mid-download progress milestones or the separate async sheet-updater yet.

---
## Required Behavior from the Master Plan

### Startup validation

Before significant discovery/download processing begins, fail early with a clear error if any required reporting column is missing.

This step should turn the plan’s required TODO into production behavior.

### Status model to use now

Use the bounded `processing_status_main` approach described in the plan.

For this step, the minimum useful statuses are:

- `discovery-in-progress`
- `download-planning-complete` or `no-new-files-to-download`, as appropriate
- `downloaded-without-errors`
- `completed-with-some-file-failures`
- `discovery-failed`
- `spreadsheet-update-failed` when necessary

`processing_status_detail` should stay compact and human-readable.

### Summary values to write now

At minimum, final writes should populate the required summary fields from the finished sequential run outcome:

- `summary_status_last_wasapi_check`
- `summary_status_downloaded_warcs_count`
- `summary_status_downloaded`
- `summary_status_server_path`

---
## Suggested Code Shape

Keep the implementation explicit and small.

Probable shape:

- add spreadsheet reporting/validation helpers in `lib/collection_sheet.py` or a small neighboring `lib/` module
- call those helpers from `lib/orchestration.py` at startup and at per-collection start/final checkpoints
- do not move business logic into `main.py`

The code should reuse existing row-identification metadata from sheet ingestion rather than inventing a second lookup path.

---
## Minimum Test Coverage

Add focused `unittest` coverage for:

- **required-column validation**
  - missing required reporting columns fail early with a clear error

- **start status write**
  - sequential collection processing sends the expected start status payload

- **final status write**
  - successful processing sends the expected final status and summary payload

- **failure-path status write**
  - discovery failure or file-failure outcomes map to the correct final status

- **sheet-write failure handling**
  - spreadsheet write failures are surfaced clearly without corrupting local manifest/file state

Likely test files:

- `warc_tracker_script/tests/test_collection_sheet.py`
- `warc_tracker_script/tests/test_orchestration.py`

---
## Out of Scope for This Step

- Trio concurrency
- dedicated async sheet-updater task
- mid-download progress milestones such as `20%`, `40%`, `60%`, `80%`
- lock/cron wrapper work
- any redesign of the existing sequential downloader/fixity flow

---
## Success Criteria

- [ ] startup validation checks for all six required reporting columns before significant processing begins
- [ ] sequential collection processing writes a start status to the spreadsheet
- [ ] sequential collection processing writes a final status plus required summary fields
- [ ] sheet-write failures are logged and surfaced without undoing local durable state
- [ ] focused `unittest` coverage exists for validation plus start/final reporting behavior

---
## Likely Follow-Up After This Step

After this step, the next best step should be:

1. implement the `Trio` flow with two dedicated download workers and a separate sheet-updater task
2. then add lock/cron hardening

---
## Handoff Notes for the Next Agent / New Session

If you are picking this up in a new session, re-read:

- `warc_tracker_script/AGENTS.md`
- `warc_tracker_script/PLAN__simplified_warc_backup_script.md`
- `warc_tracker_script/PLAN__next_single_step.md`

Quick mental model:

- `main.py` should remain thin
- `lib/orchestration.py` is the current sequential production spine
- the next implementation target is not Trio yet; it is the spreadsheet reporting contract plus start/final status integration in the sequential flow
- once that contract exists, progress batching and the async sheet-updater become much easier to add cleanly

