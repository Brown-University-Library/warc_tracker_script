# Next Single Step: Filter Planned Downloads Before Writing Download-Start Status

## Context for Future Agents

**Code-directives**: review `warc_tracker_script/AGENTS.md` before editing code.

**Plan reference**:

- `warc_tracker_script/PLAN__simplified_warc_backup_script.md`

**Recent reporting-count guidance**:

- `warc_tracker_script/tmp_recent_prompt.md`
- `warc_tracker_script/tmp_model_answer.md`

**Focus of this step**: implement Option 1 from `tmp_model_answer.md`.

The goal is to make the spreadsheet-visible denominator mean **files that still require download work now**, instead of raw
merged planned candidates that may already exist on disk by the time download-status reporting begins.

This step should fit the current sequential production flow and keep `main.py` thin.

---

## Goal of This Step

Add one authoritative pre-download filtering step so that, after merged planning is complete:

1. the code derives a filtered download list from the broader planned-candidate list
2. entries that already satisfy the current MVP "no download needed" rule are removed before download-start status is written
3. the filtered list becomes the list used for:
   - the spreadsheet-facing planned-download denominator
   - the initial `downloading-in-progress` status
   - mid-download progress milestones
   - the actual sequential download loop

This step is specifically about making the **download-work denominator** feel correct and internally consistent.

---

## Why This Is the Right Next Step

1. **It directly addresses the reported mismatch**
   - the recent prompt identified the operator-facing problem: a denominator such as `7` can include an item later skipped because
     the file already exists
   - Option 1 was chosen as the desired direction

2. **It is a small, bounded change to the current sequential flow**
   - the current production orchestrator already builds merged `planned_downloads`
   - the change is to insert one additional filtering pass before spreadsheet progress reporting and before the download loop begins

3. **It improves semantics without jumping to larger redesign work**
   - no Trio conversion is required
   - no sheet-updater task is required
   - no broader reporting-model rewrite is required

4. **It aligns with the project plan's spreadsheet philosophy**
   - the spreadsheet is a reporting surface, so its counts should reflect real remaining work as closely as practical
   - the filesystem and local state remain the source of truth

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

- do not redesign the overall planning pipeline
- do not introduce fuzzy spreadsheet wording as the primary fix
- do define one explicit helper or decision point for "still requires download work now"
- do keep the loop-level defensive skip behavior if it currently protects against small race windows

---

## Required Behavioral Policy

Use this exact policy as the implementation target.

### 1. Keep raw merged planning available conceptually

The code may continue to build the broader merged planned-candidate list exactly as it does now.

That broader list still serves an internal planning purpose, including combining:

- discovery-driven candidates
- reconciliation/retry candidates
- filename-level dedup behavior already present in the orchestrator

This step does **not** require redefining the earlier planning merge itself.

### 2. Add a new filtering stage before download-start reporting

After merged planning completes, do one pass that derives a narrower list containing only entries that still require download work
at that moment.

That filtered list should become the authoritative list for download-status reporting and loop execution.

### 3. Minimum MVP filtering rule for this step

The recent reporting-count question focused specifically on the case where a destination WARC already exists on disk.

Minimum implementation target:

- remove a planned item from the active download list when its destination WARC path already exists on disk

Important caveat from the master plan:

- the longer-term project meaning of "needs download" can also involve fixity or verification concerns
- this step should review the current code's actual behavior carefully before broadening the filter beyond existence checks

Recommendation for this step:

- match the current sequential loop's real skip behavior first
- if the loop currently skips purely on WARC existence, make the new pre-download filter use that same rule
- do **not** silently broaden the rule to include new fixity-validation logic unless the current production code already relies on it

### 4. Keep one consistent denominator after filtering

Once the filtered list is built, use its length consistently for all spreadsheet-visible download-progress counts in this collection run.

Specifically:

- `download-planning-complete` detail should reflect the filtered count if that status currently reports a file count
- the initial `downloading-in-progress` detail should use the filtered count
- coarse progress milestones should use the filtered count as their denominator
- final success/failure summaries should remain consistent with the filtered loop input and current final-reporting semantics

If any earlier planning-stage status currently exposes the broader raw candidate count, either:

- update it to the filtered count for consistency, or
- deliberately leave it unchanged only if the wording makes the distinction explicit

For this step, the preferred outcome is **one consistent spreadsheet-facing meaning**.

### 5. Preserve defensive loop behavior

Even after filtering, keep the loop-level defensive check if it currently skips existing destination files.

Reason:

- the new filter improves the denominator
- the loop-level guard still protects against small timing windows or unexpected local changes between filtering and execution

### 6. Manifest behavior should remain deliberate

This step must review how planned-download manifest entries are currently persisted before downloads begin.

Key question to answer during implementation:

- should entries removed by the new active-download filter still be persisted as planned in `state.json`, or should manifest persistence move to
  after filtering so only true active downloads are recorded for this phase?

Recommendation for this step:

- do not change manifest semantics casually
- first inspect what current tests and state-writing behavior assume
- if persistence currently happens before filtering, decide explicitly whether that remains acceptable or whether it creates the same
  denominator confusion in durable state

The code change should make this choice explicit and tested.

---

## Specific Implementation Plan

### 1. Review the current sequential planning-to-download path

Inspect the current orchestration flow to confirm:

- where discovery candidates are merged with reconciliation/retry candidates
- where planned-download manifest entries are persisted
- where `download-planning-complete` status is written
- where `downloading-in-progress` and milestone statuses are written
- where the sequential loop currently skips already-existing destination WARCs

Expected outcome of this review:

- identify one narrow insertion point for the new filter
- confirm the existing operational meaning of "skip because already present"
- avoid duplicating logic in multiple places

### 2. Identify or create one helper for active-download eligibility

Add a focused helper with a meaning like:

- planned item still requires download work now

Recommended helper responsibilities:

- accept one planned-download item
- inspect the current destination WARC path and any already-existing fields needed for the decision
- return whether the item belongs in the active download list

Guardrails:

- keep the helper small and explicit
- prefer a pure-ish helper around local path checks where practical
- avoid combining it with spreadsheet status formatting
- avoid embedding this logic directly inside `main.py`

### 3. Derive `active_downloads` from the merged planned list

After merged planning is complete, derive a filtered list such as `active_downloads`.

Recommended behavior:

- preserve the existing ordering of planned items
- filter by the new helper
- optionally record how many items were excluded because they were already present

That filtered list should become the main input to the subsequent download-reporting path.

### 4. Decide the interaction with manifest persistence

This is the most important design choice in the step.

Evaluate the two concrete options against existing code and tests:

- **Option A:** persist the broader planned list, then filter to `active_downloads` only for reporting and loop execution
- **Option B:** filter first, then persist only `active_downloads` as planned-download manifest entries

Recommendation for this step:

- prefer the option that keeps durable state and spreadsheet-visible counts aligned, unless existing recovery semantics clearly rely on the
  broader pre-filter persistence
- if the broader persistence is retained, document in code/tests why that distinction is intentional

Whichever option is chosen, add tests that lock in the intended semantics.

### 5. Update spreadsheet status writes to use the filtered denominator

Adjust the collection-level reporting path so the count visible to operators reflects `active_downloads`, not the broader raw planned list.

At minimum verify and update, if needed:

- `download-planning-complete`
- the initial `downloading-in-progress`
- coarse `20%`/`40%`/`60%`/`80%` milestone calculations
- any detail text that currently embeds planned counts

If useful, include compact wording for excluded items only if that can be done without destabilizing current status text conventions.

The primary goal is the denominator fix, not a wording redesign.

### 6. Run the sequential download loop over `active_downloads`

Change the actual loop input so it iterates over the filtered list.

Expected results:

- fewer no-op entries enter the loop
- progress counts line up with actual attempted download work
- existing defensive skip behavior remains as a backstop rather than the first place the item is excluded

### 7. Add focused tests around the new count semantics

Add or extend `unittest` coverage for the reporting-count behavior.

Minimum happy paths:

- when one merged planned item already exists on disk, the active-download denominator excludes it before `downloading-in-progress` is written
- the sequential loop runs only over the filtered active-download list

Minimum failure/edge paths:

- when no planned items are filtered out, existing behavior remains unchanged
- duplicate or reconciliation-derived candidates that survive merging but point to existing WARCs are excluded consistently
- the loop-level guard still tolerates a file appearing after filtering but before actual download execution
- manifest persistence behavior is covered according to the explicit design choice from step 4

### 8. Keep logging targeted and operator-friendly

Recommended logs:

- raw merged planned count
- filtered active-download count
- how many items were excluded because they already existed on disk
- confirmation that download-status reporting is using the filtered count

Avoid noisy per-file logs unless a failure case needs them.

---

## Likely Code Touch Points

- `warc_tracker_script/main.py`
  - only for thin orchestration wiring if needed
- `warc_tracker_script/lib/orchestration.py`
  - likely primary location for the new filter insertion, reporting-count updates, and loop input change
- `warc_tracker_script/lib/local_state.py`
  - only if manifest persistence semantics need a small additive helper or adjustment
- `warc_tracker_script/lib/storage_layout.py`
  - only if path access helpers are the cleanest place to support eligibility checks
- `warc_tracker_script/tests/test_orchestration.py`
  - likely primary location for count-semantics and loop-input tests
- related state or reporting tests
  - only if existing persistence/reporting assumptions need to be updated narrowly

Keep business logic out of `main.py` and avoid using spreadsheet wording alone as the fix.

---

## Minimum Test Coverage

Add focused `unittest` coverage for:

- a planned item whose destination WARC already exists being removed before `downloading-in-progress` status is written
- progress denominators using the filtered active-download count rather than the broader merged planned count
- the actual sequential download loop iterating over the filtered list
- no-filter cases preserving current counts and behavior
- manifest-persistence semantics matching the chosen design
- the loop-level defensive existence guard remaining intact as a backstop

If current tests already cover the planning/reporting sequence, extend those tests rather than creating heavier new integration tests unless
necessary.

---

## Out of Scope for This Step

- redesigning all spreadsheet wording
- implementing full fixity-based or verification-based "needs work" reconciliation beyond the current production rule
- Trio orchestration with download workers
- moving sheet writes behind the future dedicated sheet-updater task
- changing final summary fields that report on-disk collection totals
- broader state-model redesign beyond the specific manifest-persistence decision required for this step

---

## Success Criteria

- [ ] merged planning still occurs using the current discovery/reconciliation flow
- [ ] a new pre-download filter derives an authoritative active-download list before download-start status is written
- [ ] already-present destination WARCs are excluded from the spreadsheet-visible denominator for download progress
- [ ] the sequential loop runs over the filtered active-download list
- [ ] spreadsheet progress counts remain internally consistent from download start through milestones
- [ ] manifest-persistence semantics are explicitly chosen and covered by tests
- [ ] focused `unittest` coverage exists for at least one happy path and one edge/race-style path

---

## Likely Follow-Up After This Step

1. decide whether the active-download eligibility helper should later expand beyond plain WARC existence to cover missing/invalid fixity artifacts
2. evaluate whether spreadsheet detail text should explicitly mention excluded already-present files when that count is non-zero
3. use the same active-work semantics when the project later moves to the Trio-based worker flow

---

## Handoff Notes

If you pick this up in a new session, re-read:

- `warc_tracker_script/AGENTS.md`
- `warc_tracker_script/PLAN__simplified_warc_backup_script.md`
- `warc_tracker_script/tmp_recent_prompt.md`
- `warc_tracker_script/tmp_model_answer.md`
- `warc_tracker_script/PLAN__next_single_step.md`

Quick mental model:

- this step is about **making the visible download denominator match real remaining download work**
- keep the current sequential flow intact
- insert one new authoritative filter between merged planning and download-status reporting
- make the filtered list drive both progress reporting and the actual loop
- treat manifest persistence as an explicit design choice, not an accident
