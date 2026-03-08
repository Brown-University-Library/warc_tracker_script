# Next Single Step: Expand Sequential Spreadsheet Phase and Progress Reporting
 
 ## Context for Future Agents
 
 **Code-directives**: review `warc_tracker_script/AGENTS.md` before editing code.
 
 **Plan reference**:
 
 - `warc_tracker_script/PLAN__simplified_warc_backup_script.md`
 
 **Focus of this step**: expand the existing sequential spreadsheet-update behavior so the production flow writes richer collection-level phase/status updates and coarse mid-download progress updates.
 
 The production code already does these pieces:
 
 - validates required reporting/status columns before significant processing begins
 - writes collection-level start status updates
 - writes collection-level final status/summary updates
 - keeps the main backup flow sequential
 
 The intended addition in this step is:
 
 - write clearer intermediate collection phases during the sequential flow
 - write coarse progress milestones while downloads are in progress
 - keep the spreadsheet as a reporting/control surface rather than a source of truth
 - make the smallest clear change without starting the later Trio sheet-updater architecture
 
 ---
 ## Goal of This Step
 
 Extend the existing sequential orchestration so each processed collection reports a clearer lifecycle in the spreadsheet:
 
 1. when discovery begins
 2. when download planning finishes
 3. whether there are no files to download or downloading is underway
 4. coarse progress milestones during downloading
 5. the final outcome summary that already exists
 
 Specifically, this step should add bounded, collection-level status writes for:
 
 - `discovery-in-progress`
 - `download-planning-complete`
 - `no-new-files-to-download` when applicable
 - `downloading-in-progress` with milestone-style `processing_status_detail`
 
 That is the whole feature for this step.
 
 ---
 ## Why This Is the Right Next Step
 
 1. **It is the explicit next unfinished slice in the master plan**
    - step 12 in `PLAN__simplified_warc_backup_script.md` already marks required-column validation and start/final writes as done
    - the plan names richer sequential phase/status reporting and mid-download progress reporting as the next slice
 
 2. **It fits the current architecture**
    - the production flow is already sequential and working
    - the plan explicitly says the Trio architecture is not implemented yet
    - this work improves visibility without introducing concurrency complexity
 
 3. **It improves cron-time observability**
    - operators can tell whether a collection is in discovery, planning, no-op, or downloading
    - operators can see bounded progress without turning the sheet into a per-file event log
 
 4. **It prepares later async work**
    - a clearer sequential status model will make the later dedicated sheet-updater task easier to design
    - this step clarifies what events the future async updater will need to handle
 
 ---
 ## Guiding Constraints from the Project Plan
 
 This step should follow these project rules from `PLAN__simplified_warc_backup_script.md`:
 
 - the local filesystem and `state.json` remain the source of truth
 - the spreadsheet is for reporting and control, not correctness
 - writes should stay controlled and not become highly chatty
 - progress detail should use coarse, stable milestone text rather than per-file chatter
 - the current sequential orchestration remains the execution path for now
 
 Recommended status model from the master plan:
 
 - `pending`
 - `discovery-in-progress`
 - `download-planning-complete`
 - `downloading-in-progress`
 - `no-new-files-to-download`
 - final outcomes already supported by current code
 
 Recommended progress-detail style from the master plan:
 
 - milestone updates such as `20% (3/15 files)`
 - compact, human-readable detail text
 - no noisy per-file status writes unless later proven necessary
 
 ---
 ## Specific Implementation Plan
 
 ### 1. Review the current sheet-update helpers and status-writing flow
 
 Before editing behavior, inspect the current production code path that:
 
 - validates required reporting/status columns
 - writes the initial collection-level status
 - writes the final collection-level summary and outcome
 
 The purpose of this review is to identify the existing abstraction boundary so the new intermediate writes re-use current helper functions instead of duplicating spreadsheet-write code.
 
 Expected outcome of this review:
 
 - identify the helper or helpers in `lib/orchestration.py` and related spreadsheet modules that already write collection status
 - confirm how `processing_status_main`, `processing_status_detail`, and `summary_status_*` values are currently assembled
 - keep `main.py` unchanged unless a tiny orchestration call-site adjustment is required
 
 ### 2. Define one explicit sequential phase lifecycle in code
 
 Add or consolidate a small, explicit set of status constants or enum-like values used by the sequential flow.
 
 The first slice should cover these intermediate statuses:
 
 - `discovery-in-progress`
 - `download-planning-complete`
 - `downloading-in-progress`
 - `no-new-files-to-download`
 
 Important design rule:
 
 - do not generate ad hoc `processing_status_main` strings inline at many call sites
 - define the allowed values in one place so future spreadsheet writes stay consistent
 
 This should match the master plan's recommendation that `processing_status_main` remain bounded and explicit.
 
 ### 3. Add a status write when discovery begins
 
 In the current sequential `process_collection_job()` flow, write an early collection update when WASAPI discovery for that collection starts.
 
 Recommended behavior:
 
 - `processing_status_main = discovery-in-progress`
 - `processing_status_detail` should be short and stable, such as a compact indication that discovery is running
 
 This status should be written after the collection is accepted for processing and before WASAPI enumeration begins.
 
 ### 4. Add a status write after download planning completes
 
 After the code has:
 
 - completed discovery successfully
 - built the list of planned downloads for that collection
 - determined whether work exists
 
 write a planning-complete update.
 
 Recommended behavior:
 
 - `processing_status_main = download-planning-complete`
 - `processing_status_detail` should summarize the planned work in a compact way
 
 Suggested detail examples:
 
 - `0 files planned`
 - `3 files planned`
 - `15 files planned`
 
 This creates a clear separation between discovery and actual download execution.
 
 ### 5. Split the post-planning path into no-op versus active download reporting
 
 After planning completes, branch status handling based on whether any downloads are needed.
 
 If no downloads are needed:
 
 - write `processing_status_main = no-new-files-to-download`
 - set `processing_status_detail` to a compact reason or context, consistent with the master plan
 - then continue into the existing final summary/outcome handling
 
 If one or more downloads are needed:
 
 - write `processing_status_main = downloading-in-progress`
 - set the initial `processing_status_detail` to something like `0% (0/N files)` or `starting (0/N files)`
 - then begin the existing sequential download/fixity loop
 
 The code should avoid multiple ambiguous branches that can produce inconsistent status combinations.
 
 ### 6. Add a coarse progress-milestone helper for the sequential download loop
 
 Add a small helper that decides whether a progress update should be written after a completed file attempt.
 
 This helper should:
 
 - accept total planned file count
 - accept completed file count
 - compute coarse milestone thresholds
 - avoid duplicate writes for the same milestone
 - return either no update or a compact progress-detail string
 
 Recommended first-slice milestone policy:
 
 - write at download start
 - write at `20%`, `40%`, `60%`, and `80%`
 - do not write a separate `100%` progress update if the existing final outcome write immediately follows and makes it redundant
 
 Recommended detail format:
 
 - `20% (3/15 files)`
 - `40% (6/15 files)`
 - `60% (9/15 files)`
 
 Important design rule:
 
 - progress should be based on completed file attempts moving through the loop, not just successful downloads
 - this keeps progress visible even when some files fail
 
 ### 7. Write progress updates from the existing sequential download loop
 
 Integrate the milestone helper into the current sequential download/fixity loop with the smallest clear code change.
 
 Recommended behavior:
 
 - after each file attempt finishes, update loop counters
 - ask the helper whether a new milestone has been reached
 - if yes, send one spreadsheet status write using:
   - `processing_status_main = downloading-in-progress`
   - `processing_status_detail = <milestone text>`
 
 This approach preserves the current execution model while adding bounded visibility.
 
 ### 8. Keep final outcome writes authoritative
 
 Do not redesign the existing final outcome reporting in this step unless a small adjustment is needed for consistency.
 
 The current final write should remain the authoritative end-of-collection state.
 
 The new intermediate writes should lead cleanly into the existing final outcomes, such as:
 
 - `downloaded-without-errors`
 - `completed-with-some-file-failures`
 - `discovery-failed`
 - `spreadsheet-update-failed` if the existing code already uses that path
 
 The main point is to fill the visibility gap during processing, not to redesign end-state reporting.
 
 ### 9. Add logging aligned with spreadsheet phase changes
 
 Add or adjust log messages so they mirror the new spreadsheet phases.
 
 Logs should make it easy to correlate:
 
 - when discovery started
 - when planning completed and how many files were planned
 - when downloads began
 - when a progress milestone was written
 - when the final outcome was written
 
 This keeps sheet visibility and log visibility aligned during debugging and cron monitoring.
 
 ---
 ## Likely Code Touch Points
 
 - `warc_tracker_script/lib/orchestration.py`
   - add or consolidate bounded status constants
   - extend the sequential collection-processing flow with intermediate status writes
   - add a progress-milestone helper
   - call the existing sheet-write helper at controlled points in the download loop
 - spreadsheet-related helpers already used by orchestration
   - only if current helper boundaries make a small refactor useful
 - `warc_tracker_script/tests/test_orchestration.py`
   - add focused tests for phase transitions and progress-milestone behavior
 - spreadsheet-update tests, if present elsewhere in the repo
   - only if needed to keep status-writing behavior covered at the right layer
 
 Keep `main.py` thin and avoid any new architectural layer unless a small helper extraction clearly reduces duplication.
 
 ---
 ## Minimum Test Coverage
 
 Add focused `unittest` coverage for:
 
 - collection processing writes `discovery-in-progress` before WASAPI enumeration begins
 - successful planning with zero planned downloads writes `download-planning-complete` followed by `no-new-files-to-download`
 - successful planning with one or more downloads writes `download-planning-complete` followed by `downloading-in-progress`
 - the sequential download loop emits progress updates only at the chosen milestone boundaries
 - progress detail text uses the expected compact format such as `40% (6/15 files)`
 - duplicate milestone writes are not emitted when multiple completed counts fall within the same milestone bucket
 - final outcome writes still occur and remain consistent with current success/failure behavior
 
 If the existing tests mock sheet writes, prefer extending those mocks rather than introducing broader integration tests for this slice.
 
 ---
 ## Out of Scope for This Step
 
 - moving sheet writes behind the future dedicated sheet-updater task
 - implementing Trio orchestration
 - adding per-file spreadsheet chatter
 - changing the source-of-truth model away from local filesystem plus `state.json`
 - redesigning download retry behavior
 - lock or cron-wrapper hardening
 - adding new worksheet columns beyond the required contract already described in the master plan
 
 ---
 ## Success Criteria
 
 - [ ] the sequential flow writes `discovery-in-progress` when collection discovery starts
 - [ ] the sequential flow writes `download-planning-complete` after planning finishes
 - [ ] collections with no planned downloads write `no-new-files-to-download`
 - [ ] collections with planned downloads write `downloading-in-progress` and coarse milestone updates
 - [ ] progress updates are bounded to stable milestone checkpoints rather than per-file chatter
 - [ ] existing final outcome reporting still works correctly
 - [ ] focused `unittest` coverage exists for the new intermediate status/progress behavior
 
 ---
 ## Likely Follow-Up After This Step
 
 1. move the same phase/progress events behind the later dedicated sheet-updater task
 2. decide whether progress detail should be based on completed attempts or only successful downloads if operator feedback suggests a change
 3. add lock and cron-wrapper hardening once reporting visibility is good enough for production monitoring
 4. implement the later Trio architecture after the sequential event model feels stable
 
 ---
 ## Handoff Notes
 
 If you pick this up in a new session, re-read:
 
 - `warc_tracker_script/AGENTS.md`
 - `warc_tracker_script/PLAN__simplified_warc_backup_script.md`
 - `warc_tracker_script/PLAN__next_single_step.md`
 
 Quick mental model:
 
 - this step is about **making the current sequential flow more visible in the spreadsheet**
 - the code already validates required columns and writes start/final collection updates
 - the missing slice is the in-between reporting: discovery, planning, no-op, and coarse download progress
 - keep the change small, bounded, and sequential
 - do not jump ahead to Trio yet
