# Next Single Step: Add a True Post-Discovery Evaluation Step for Download Need

## Context for Future Agents

**Code-directives**: review `warc_tracker_script/AGENTS.md` before editing code.

**Plan reference**:

- `warc_tracker_script/PLAN__simplified_warc_backup_script.md`

**Recent evaluation guidance**:

- `warc_tracker_script/tmp_recent_prompt.md`
- `warc_tracker_script/tmp_model_answer.md`

**Focus of this step**: after WASAPI discovery and current merge/dedup planning, add a real evaluation stage that determines whether each
candidate still requires backup work.

This step is **not** just an existence-based filter. The evaluation should become the authoritative decision point for whether a file belongs
in the active download list used for manifest persistence, spreadsheet progress counts, and the sequential download loop.

This step should fit the current sequential production flow and keep `main.py` thin. I am also following the prior preference memory that
you prefer building sequentially from `main.py` while keeping it orchestration-focused.

---

## Goal of This Step

Add one authoritative post-discovery evaluation stage so that, after discovery, reconciliation retry planning, and filename-level dedup are
complete:

1. the code evaluates each planned candidate against the local filesystem and local backup-completeness signals
2. the code produces an `active_downloads` list containing only files that still require work
3. the evaluated `active_downloads` list becomes the list used for:
   - planned-download manifest persistence
   - `download-planning-complete`
   - `downloading-in-progress`
   - coarse progress milestones
   - the actual sequential download/fixity loop

The point is to make the post-discovery list a true **needs-work evaluation result**, not merely a cosmetic reporting filter.

---

## Why This Is the Right Next Step

1. **It matches the master plan’s stated backup rule**
   - `PLAN__simplified_warc_backup_script.md` already says a file may need work not only when the WARC is missing, but also when size
     verification fails, fixity sidecars are missing or invalid, or a prior failed attempt should be retried
   - the current denominator discussion now points directly at implementing that intended rule more explicitly in production

2. **It makes reporting semantics honest**
   - if spreadsheet-visible counts are meant to describe real remaining work, they should be driven by the same deeper evaluation that the
     backup process itself trusts
   - that avoids a mismatch where reporting says "no work needed" but deeper fixity or retry conditions still mean work remains

3. **It improves durable state semantics**
   - if `state.json` persists only the evaluated active-download list for this phase, durable planning state will better reflect what the run
     truly intended to do after local evaluation
   - broader raw discovery counts can still be logged without becoming authoritative manifest state

4. **It remains a bounded sequential-flow improvement**
   - this does not require Trio or a sheet-updater task
   - it should primarily refactor the decision point between planning and execution in the current sequential orchestrator

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

- do not redesign the overall WASAPI discovery path
- do not use wording-only fixes as a substitute for better evaluation logic
- do define one explicit evaluation helper or helper family for "still requires backup work now"
- do keep cheap defensive loop checks even after the new evaluation stage exists

---

## Required Behavioral Policy

Use this exact policy as the implementation target.

### 1. Keep raw discovery and merge behavior conceptually separate from evaluated download need

The current broader candidate-building flow may continue to do what it already does:

- WASAPI discovery-driven candidate creation
- reconciliation/retry candidate creation from `state.json`
- filename-level merge/dedup behavior

But that broader merged candidate list should no longer be treated as the authoritative answer to "what still needs download work?"

Instead, authoritative download need should be determined by a later evaluation stage.

### 2. Add a true evaluation stage before manifest persistence and download-start reporting

After merged planning completes, evaluate each candidate against the current local state of the collection.

This evaluation should determine whether the candidate:

- needs download work
- needs fixity/verification repair work that should still flow through the existing download/fixity path
- or is already fully satisfied locally and should be excluded from active download work

The result should be an evaluated `active_downloads` list.

### 3. Minimum evaluation dimensions for this step

The project plan already names the important dimensions. The new evaluation stage should review and align with the current production data
available for these checks:

- whether the local WARC file exists
- whether local size verification passes or fails when the needed size information is available
- whether required SHA-256/fixity sidecars exist and are valid enough for the current production rule
- whether the manifest indicates a prior failed attempt whose retry remains allowed

This does **not** necessarily mean inventing brand-new deep validation rules. It does mean the step should explicitly review how much of each
dimension the current code can already evaluate cheaply and deterministically.

Recommendation for this step:

- make the evaluation rule as deep as current production metadata and helpers reasonably support
- avoid speculative or expensive validation beyond what the repository already models clearly
- if one of the plan’s ideal checks is not currently implementable from available data, document that limitation in code/tests and keep the
  rule explicit rather than implicit

### 4. Choose evaluated active downloads as the authoritative planned-download list for this phase

For this step, Option B should be treated as the target design:

- persist planned-download manifest entries only for the evaluated `active_downloads` list
- do not persist the broader pre-evaluation merged candidate list as if it were authoritative planned-download state

The broader discovery/merge counts may still be logged for observability.

This means the evaluated list is not just a filter layered on reporting. It is the authoritative run-intent list for this stage of the
sequential production flow.

### 5. Keep one consistent spreadsheet-facing denominator after evaluation

Once `active_downloads` is built from the full evaluation stage, use its length consistently for spreadsheet-visible progress counts.

Specifically:

- `download-planning-complete` should reflect the evaluated active-download count if it reports a file count
- the initial `downloading-in-progress` status should use the evaluated count
- coarse progress milestones should use the evaluated count as their denominator
- no-new-work cases should flow from the evaluated result, not the broader raw merged candidate list

### 6. Preserve defensive execution behavior

Even after the new evaluation stage, keep cheap defensive checks in the sequential loop where they protect against timing windows or local
changes between evaluation and execution.

The evaluation should become the primary decision point, but the loop may still defensively skip or re-handle edge cases.

---

## Specific Implementation Plan

### 1. Review the current planning-to-execution path in `lib/orchestration.py`

Inspect the current sequential flow to confirm:

- where WASAPI-discovered records become planned candidates
- where reconciliation/retry candidates are added
- where merged planned downloads are deduplicated
- what metadata is available on each planned item for local evaluation
- where planned-download manifest entries are currently persisted
- where `download-planning-complete`, `downloading-in-progress`, and milestone statuses are written
- what the current download loop does when a destination WARC already exists or when other local-state anomalies are encountered

Expected outcome of this review:

- identify one narrow insertion point for the new evaluation stage
- identify the current data available for size and fixity-related checks
- avoid duplicating logic across evaluation, reporting, and loop execution

### 2. Identify or create one explicit helper surface for local backup-need evaluation

Add a focused helper or helper family with a meaning like:

- planned candidate still requires backup work now

Recommended responsibilities:

- accept one planned-download candidate plus the local paths/manifest data needed for evaluation
- determine whether the file is already locally complete enough to skip
- determine whether a missing/invalid local artifact means work is still needed
- return a clear evaluation result rather than only a boolean when useful

Recommended result shape:

- `needs_work: bool`
- a bounded reason/value such as:
  - `missing_warc`
  - `size_mismatch`
  - `missing_fixity`
  - `invalid_fixity`
  - `retry_after_prior_failure`
  - `already_complete`

Guardrails:

- keep this logic out of `main.py`
- keep the evaluation helper separate from spreadsheet status formatting
- keep the reason vocabulary explicit and bounded

### 3. Decide the exact MVP meaning of each evaluation check

Before editing behavior, lock down what each check means in current production terms.

At minimum answer these questions from code review:

- what source of expected size is available on a planned candidate, and is it always present?
- what makes a fixity sidecar "valid enough" for this step: existence only, parseability, checksum-content consistency, or something narrower?
- when the manifest says a prior attempt failed, what exact conditions allow retry today?
- if the WARC exists but fixity is missing, should the file remain in `active_downloads` under the current sequential loop design?

Recommendation for this step:

- lock the implementation to the strongest rule that is already supported by current code and tests
- do not invent unverifiable validation requirements
- if any ideal rule from the master plan cannot yet be enforced, document the current narrower rule in tests

### 4. Build evaluated `active_downloads` from the merged candidate list

After merged planning completes, evaluate every candidate and build `active_downloads` from only those items whose evaluation says work is
still needed.

Recommended behavior:

- preserve existing candidate ordering
- preserve existing filename-level dedup outcomes before evaluation
- optionally accumulate summary counts by evaluation reason for logging

This evaluated list should become the main input to the remainder of the collection-processing path.

### 5. Move planned-download manifest persistence to after evaluation

This is now the chosen design for the step.

Implement Option B explicitly:

- persist planned-download manifest entries only for evaluated `active_downloads`
- do not persist the broader raw merged list as planned-download state for this phase

Recommended complementary behavior:

- log raw merged planned count
- log evaluated active-download count
- log summary exclusion reasons such as already-complete or missing-fixity-driven inclusion

This preserves observability without diluting durable manifest meaning.

### 6. Update spreadsheet status writes to use the evaluated denominator

Adjust the collection-level reporting path so spreadsheet-visible counts reflect the evaluated `active_downloads` list.

At minimum verify and update, if needed:

- `download-planning-complete`
- `downloading-in-progress`
- coarse `20%`/`40%`/`60%`/`80%` milestone calculations
- `no-new-files-to-download`

If current status detail text includes file counts, those counts should now refer to evaluated active work, not raw discovered candidates.

### 7. Run the existing sequential download/fixity path over evaluated `active_downloads`

Change the actual loop input so it iterates over the evaluated active-work list.

Important design note:

- if the evaluation decides that missing/invalid fixity means work remains, verify whether the current sequential loop can satisfy that work
  as-is or whether the loop assumes downloading is always needed first

If current production code cannot repair some non-download-only condition without re-downloading, document that explicitly and keep behavior
aligned with the current production path rather than inventing a partially implemented branch.

### 8. Add focused tests around the evaluation semantics

Add or extend `unittest` coverage for the new authoritative evaluation step.

Minimum happy paths:

- a missing WARC stays in `active_downloads`
- a fully complete local file is excluded from `active_downloads`
- a file with missing fixity remains in `active_downloads` if the chosen current-rule semantics say it still needs work
- a retry-eligible prior failure remains in `active_downloads`

Minimum edge/failure paths:

- a file with size mismatch remains in `active_downloads` when expected size metadata is available
- missing expected-size metadata follows the explicitly chosen fallback rule
- evaluated active-download count drives `download-planning-complete` and `downloading-in-progress`
- only evaluated `active_downloads` are persisted as planned-download manifest entries
- defensive loop checks still tolerate a local file appearing after evaluation but before execution

### 9. Keep logging targeted and diagnostic

Recommended logs:

- raw merged candidate count
- evaluated active-download count
- excluded already-complete count
- included-by-reason counts such as missing WARC, size mismatch, missing fixity, invalid fixity, retry after failure
- confirmation that manifest persistence and progress reporting use evaluated active downloads

Avoid noisy per-file logging except where current failure diagnostics already expect it.

---

## Likely Code Touch Points

- `warc_tracker_script/main.py`
  - only for thin orchestration wiring if needed
- `warc_tracker_script/lib/orchestration.py`
  - likely primary location for inserting the evaluation stage, moving manifest persistence, and updating reporting counts
- `warc_tracker_script/lib/local_state.py`
  - possibly for manifest inspection helpers or additive state-evaluation helpers
- `warc_tracker_script/lib/fixity.py`
  - only if the cleanest fixity-sidecar validation logic already belongs there or should be exposed from there
- `warc_tracker_script/lib/storage_layout.py`
  - only if local path derivation/access helpers need a narrow addition
- `warc_tracker_script/tests/test_orchestration.py`
  - likely primary location for evaluation-semantics, persistence-order, and reporting-count tests
- related local-state or fixity tests
  - only if helper-level evaluation logic is split into narrower units

Keep business logic out of `main.py` and keep the evaluation rule explicit.

---

## Minimum Test Coverage

Add focused `unittest` coverage for:

- missing-WARC candidates being retained in evaluated active work
- already-complete files being excluded from evaluated active work
- missing or invalid fixity artifacts affecting evaluated active work according to the chosen current-rule semantics
- size mismatch affecting evaluated active work when expected-size metadata exists
- retry-eligible prior failures being retained in evaluated active work
- planned-download manifest persistence happening after evaluation and only for `active_downloads`
- spreadsheet progress denominators using evaluated active-download counts rather than raw merged candidate counts
- loop-level defensive guards remaining intact after the new evaluation step

If current tests already cover the planning/reporting sequence, extend those tests rather than creating heavier new integration tests unless
necessary.

---

## Out of Scope for This Step

- redesigning the overall WASAPI discovery mechanism
- inventing new remote checksum-comparison behavior
- Trio orchestration with download workers
- moving sheet writes behind the future dedicated sheet-updater task
- broader database/state redesign beyond the specific persistence-order and evaluation semantics for this step
- large-scale wording redesign for spreadsheet statuses beyond making counts semantically correct

---

## Success Criteria

- [ ] merged planning still occurs using the current discovery/reconciliation flow
- [ ] a new explicit post-discovery evaluation stage determines whether each candidate still requires backup work
- [ ] the evaluation uses current-production-meaningful checks for WARC existence, size/fixity availability where supported, and retry status
- [ ] only evaluated `active_downloads` are persisted as planned-download manifest entries for this phase
- [ ] spreadsheet progress counts use the evaluated active-download denominator
- [ ] the sequential loop runs over evaluated `active_downloads`
- [ ] focused `unittest` coverage exists for at least one happy path and one edge case in each major evaluation category

---

## Likely Follow-Up After This Step

1. decide whether any fixity-repair conditions should eventually be handled without re-downloading when the current sequential architecture allows it
2. decide whether spreadsheet detail text should expose exclusion and inclusion reasons in compact form
3. reuse the same evaluation semantics when the project later moves to the Trio-based worker architecture

---

## Handoff Notes

If you pick this up in a new session, re-read:

- `warc_tracker_script/AGENTS.md`
- `warc_tracker_script/PLAN__simplified_warc_backup_script.md`
- `warc_tracker_script/tmp_recent_prompt.md`
- `warc_tracker_script/tmp_model_answer.md`
- `warc_tracker_script/PLAN__next_single_step.md`

Quick mental model:

- this step is about **making post-discovery planning become a true evaluation of backup need**
- raw discovery/merge output is no longer the final answer
- evaluated `active_downloads` should drive persistence, reporting, and execution
- durable state should reflect true run intent after local evaluation
- keep the rule explicit, testable, and aligned with what current production code can actually verify
