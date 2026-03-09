# Next Single Step: Add Spreadsheet Status Coordination Check for Non-`cron_locked` Runs

## Context for Future Agents

**Code-directives**: review `warc_tracker_script/AGENTS.md` before editing code.

**Plan reference**:

- `warc_tracker_script/PLAN__simplified_warc_backup_script.md`

**Recent coordination guidance**:

- `warc_tracker_script/tmp_recent_prompt.md`
- `warc_tracker_script/tmp_model_answer.md`

**Focus of this step**: implement a startup spreadsheet-status coordination check that runs when `RUN_COORDINATION_MODE` is absent or has any value other than `cron_locked`.

The goal is to preserve the planned split between:

- a **hard** guard for the scheduled production path via wrapper locking
- a **soft** guard for manual or local runs via spreadsheet preflight status inspection

This step should fit the current sequential production flow and keep `main.py` thin.

---

## Goal of This Step

Add a pre-processing coordination check with this policy:

1. if `RUN_COORDINATION_MODE=cron_locked`, skip the spreadsheet running-status check and continue
2. otherwise, read the spreadsheet before significant processing begins
3. inspect collection-row `processing_status_main` values
4. if any row is in an explicitly defined in-progress state, refuse to start the run

This check should happen early enough that a manual or local run does not begin WASAPI discovery or download work when another run appears active.

That is the whole feature for this step.

---

## Why This Is the Right Next Step

1. **It matches the recent coordination decision**
   - the recent prompt/answer settled on `RUN_COORDINATION_MODE=cron_locked` as the clearer control signal
   - the spreadsheet check is intentionally a soft guard for non-cron invocations

2. **It aligns with the master plan's remaining hardening work**
   - `PLAN__simplified_warc_backup_script.md` lists lock/cron-wrapper hardening as not yet implemented
   - this step handles the code-side coordination policy without jumping ahead to the full wrapper implementation

3. **It is a small, bounded addition to the current sequential flow**
   - the spreadsheet ingestion and required-column validation already exist
   - this step adds one preflight decision before collection processing begins

4. **It reduces accidental overlap during manual development use**
   - local/manual runs are the likely path that can bypass wrapper locking
   - checking the spreadsheet first is useful protection against that weaker path

---

## Guiding Constraints from the Project Plan and Repo Instructions

This step should follow these existing constraints:

- keep `main.py` simple and orchestration-focused
- put substantive logic in helper modules or top-level helpers
- keep the local filesystem and `state.json` as the source of truth
- treat the spreadsheet as reporting/control, not correctness
- make the smallest correct change that satisfies the request
- use focused `unittest` coverage for the happy path and at least one edge/failure path

Interpretation for this step:

- do not turn the spreadsheet check into a real lock manager
- do not use fuzzy text matching against status cells
- do define a small explicit set of in-progress spreadsheet statuses in code
- do fail early before discovery/download work starts when the check says a run appears active

---

## Required Behavioral Policy

Use this exact policy as the implementation target.

### 1. Coordination-mode decision

- read `RUN_COORDINATION_MODE` from the environment during startup configuration
- if the value is exactly `cron_locked`, skip the spreadsheet-status coordination preflight
- if the variable is missing, empty, or any other value, run the spreadsheet-status coordination preflight

Important rule:

- the mode check should be exact-string based
- do not broaden `cron_locked` matching to truthy values or partial matches

### 2. Spreadsheet preflight decision

For non-`cron_locked` runs:

- load the spreadsheet data using the existing collection-sheet pipeline
- locate the canonical spreadsheet field for collection-level main processing status
- inspect all relevant collection rows that can participate in this run surface
- if any row has a value in the bounded in-progress set, abort before significant processing begins

### 3. In-progress status vocabulary

Define one explicit code-level set for statuses that mean "a run may currently be active."

Recommended initial set:

- `discovery-in-progress`
- `downloading-in-progress`

Possible inclusion to decide during implementation review:

- `download-planning-complete`

Recommendation for this step:

- start with the narrowest conservative set of definitely active statuses
- only include `download-planning-complete` if the current sequential flow can leave that status visible while work is still truly underway

Do not treat these as in-progress without explicit reasoning:

- `pending`
- `no-new-files-to-download`
- `downloaded-without-errors`
- `completed-with-some-file-failures`
- `discovery-failed`
- `spreadsheet-update-failed`
- `skipped-invalid-collection-row`

### 4. Abort behavior

When an in-progress spreadsheet value is found during a non-`cron_locked` run:

- stop before WASAPI discovery or download planning begins
- raise or return a clear operational error
- log which in-progress statuses were found
- include enough context to explain that the run was blocked by spreadsheet coordination policy

Recommended message shape:

- say that non-`cron_locked` runs must not start when spreadsheet in-progress statuses are present
- include the blocking status values and, if practical, the related collection ids

### 5. Missing or malformed status values

For this step, the spreadsheet check should remain strict but practical.

Recommended rule:

- missing or blank `processing_status_main` values are not themselves blocking
- unrecognized non-blank values should be logged, but should not automatically block unless they exactly match the in-progress set

This keeps the check explicit and avoids introducing brittle heuristics.

---

## Specific Implementation Plan

### 1. Review the current startup and orchestration entry path

Inspect how the script currently does the following:

- loads env vars and config in `main.py`
- creates clients or dependencies
- loads spreadsheet rows
- validates required reporting columns
- begins per-collection processing

Expected outcome of this review:

- identify the narrowest insertion point for the coordination preflight
- confirm that the preflight can run before expensive work begins
- keep `main.py` as a thin orchestrator rather than embedding the spreadsheet-scan logic there

### 2. Identify or create one helper that reads coordination mode

Add a small helper or config field that exposes whether the run is in trusted `cron_locked` mode.

Recommended shape:

- a helper that returns the raw coordination mode string or a small normalized value
- orchestration code uses that helper to branch between skip-check and run-check behavior

Guardrails:

- avoid scattering direct `os.environ` reads across multiple modules
- avoid naming that implies machine identity rather than invocation mode

### 3. Identify or create one helper that detects blocking spreadsheet statuses

Implement a focused helper that accepts normalized collection-row records and returns a summary of blocking in-progress rows.

Recommended helper responsibilities:

- read the canonical `processing_status_main` field from each row
- normalize comparable string values the same way the sheet layer already normalizes fields when practical
- compare against one explicit in-progress status set
- return enough detail for logging and for a user-facing exception/error message

Recommended helper output:

- whether a blocking status was found
- the distinct blocking status values found
- optionally the related collection ids or row references

Important guardrails:

- keep spreadsheet API access outside the pure status-evaluation helper when possible
- do not combine the helper with download planning or status writing logic

### 4. Insert the coordination preflight before significant processing begins

At the current startup/orchestration level:

- if `RUN_COORDINATION_MODE=cron_locked`, log that spreadsheet coordination preflight is being skipped because the invocation is trusted and hard-locked
- otherwise, run the spreadsheet-status scan before collection processing starts
- abort immediately if blocking statuses are found

Place this preflight after the minimal startup needed to read the spreadsheet, but before:

- WASAPI discovery
- download planning
- downloading/fixity work
- collection-level status transitions for the current run

This placement matters because the check is meant to prevent accidental parallel work, not merely report it.

### 5. Decide the exact spreadsheet row scope for the preflight

Before coding, confirm whether the check should inspect:

- all collection rows in the relevant worksheet, or
- only rows that would otherwise be considered valid/active candidates for processing

Recommendation for this step:

- inspect the same normalized collection-row surface the orchestrator already trusts for collection work
- do not invent a second ad hoc parsing path only for this preflight

Practical interpretation:

- if the sheet-ingestion layer already produces a normalized set of rows with canonical fields, reuse that result
- if invalid rows are already skipped before processing, only broaden the scan if there is a strong reason that a skipped row can still signal active work

### 6. Define the failure/reporting contract clearly

When the preflight blocks a run, the code should produce:

- a clear log message
- a deterministic exception or return-path failure
- no partial processing side effects from the current invocation

Recommended implementation target:

- one dedicated error path for coordination refusal
- message includes the coordination mode and the blocking statuses found
- if practical, include a compact list of affected collection ids for debugging

### 7. Add focused tests around the branching behavior

Add or extend `unittest` coverage for the coordination logic.

Minimum happy paths:

- `RUN_COORDINATION_MODE=cron_locked` skips the spreadsheet-status scan and processing may continue
- non-`cron_locked` mode with no blocking spreadsheet statuses allows processing to continue

Minimum failure/edge paths:

- missing `RUN_COORDINATION_MODE` with at least one `discovery-in-progress` row blocks the run
- non-`cron_locked` mode with at least one `downloading-in-progress` row blocks the run
- unrecognized status text does not block unless it exactly matches a configured in-progress value
- blank/missing status values do not block by themselves

If the implementation includes `download-planning-complete` as a blocking state, add a test that locks that decision in explicitly.

### 8. Add targeted logging for operator clarity

Logging should make the preflight easy to understand in cron and manual contexts.

Recommended logs:

- the resolved coordination mode at startup
- whether the spreadsheet coordination check is being skipped or executed
- how many blocking rows were found
- what blocking statuses were found
- whether the run was refused before processing began

Avoid overly chatty per-row logging unless needed for a failure message.

---

## Likely Code Touch Points

- `warc_tracker_script/main.py`
  - only for thin orchestration/config wiring if needed
- `warc_tracker_script/lib/orchestration.py`
  - likely primary insertion point for startup coordination branching
- `warc_tracker_script/lib/collection_sheet.py`
  - only if a small additive helper is needed to expose canonical status-field access cleanly
- configuration/env-loading helpers already used by the current flow
  - if the cleanest place to expose `RUN_COORDINATION_MODE` is there
- `warc_tracker_script/tests/test_orchestration.py`
  - likely primary location for branching and preflight-behavior tests
- any existing sheet-ingestion tests
  - only if field normalization or status extraction needs a narrow helper test

Keep business logic out of `main.py` and avoid introducing a parallel coordination subsystem.

---

## Minimum Test Coverage

Add focused `unittest` coverage for:

- a trusted `cron_locked` invocation that bypasses spreadsheet-status scanning
- a non-`cron_locked` invocation that proceeds when no in-progress rows are present
- a non-`cron_locked` invocation that blocks on `discovery-in-progress`
- a non-`cron_locked` invocation that blocks on `downloading-in-progress`
- blank or missing status cells not blocking the run
- unrecognized status values being logged or tolerated without blocking
- the preflight happening before any collection discovery/download work begins

If current tests already mock orchestration entry points, extend those tests rather than building a heavier integration-style test unless necessary.

---

## Out of Scope for This Step

- implementing the actual cron wrapper or `flock` shell script
- replacing spreadsheet coordination with a real distributed lock
- moving sheet writes behind the future dedicated sheet-updater task
- Trio orchestration with download workers
- changing the current bounded status vocabulary beyond what is needed to define blocking in-progress values
- redesigning final spreadsheet summary fields
- making spreadsheet status the source of truth for correctness

---

## Success Criteria

- [ ] when `RUN_COORDINATION_MODE=cron_locked`, the script skips the spreadsheet-status coordination check
- [ ] when `RUN_COORDINATION_MODE` is missing or any non-`cron_locked` value, the script runs a spreadsheet-status coordination preflight
- [ ] the preflight blocks the run if any row is in an explicitly defined in-progress status
- [ ] the block happens before WASAPI discovery or download work begins
- [ ] the blocking rule is exact and bounded, not fuzzy-text based
- [ ] focused `unittest` coverage exists for skip, allow, and block cases

---

## Likely Follow-Up After This Step

1. implement the actual cron wrapper so scheduled production runs always set `RUN_COORDINATION_MODE=cron_locked` under `flock`
2. decide whether `download-planning-complete` should formally count as a blocking in-progress coordination state
3. later move spreadsheet writes behind the dedicated sheet-updater task without changing this startup coordination policy

---

## Handoff Notes

If you pick this up in a new session, re-read:

- `warc_tracker_script/AGENTS.md`
- `warc_tracker_script/PLAN__simplified_warc_backup_script.md`
- `warc_tracker_script/tmp_recent_prompt.md`
- `warc_tracker_script/tmp_model_answer.md`
- `warc_tracker_script/PLAN__next_single_step.md`

Quick mental model:

- this step is about **startup coordination policy for manual/local runs**
- `cron_locked` means the invocation is already trusted and hard-locked by the wrapper
- all other invocations should first scan spreadsheet in-progress statuses
- keep the check explicit, early, and small
- do not turn the spreadsheet into a real lock manager

