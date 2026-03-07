# Next Single Step: Simple Option-1 First-Run Backfill Mode

## Context for Future Agents

**Code-directives**: review `warc_tracker_script/AGENTS.md` before editing code.

**Plan references**:

- `warc_tracker_script/PLAN__handling_historical_warcs.md`
- `warc_tracker_script/PLAN__simplified_warc_backup_script.md`

**Focus of this step**: implement only **Option 1** from `PLAN__handling_historical_warcs.md`.

The intended behavior is simple:

- if a collection has no local checkpoint yet, run in **download-everything / full historical backfill** mode
- if a collection already has a checkpoint, run in normal **30-day overlap-window incremental** mode

This should be implemented with the smallest clear change in the existing sequential flow.

---
## Goal of This Step

Add one simple mode switch to the current orchestration:

1. read the collection's local `state.json`
2. check whether `enumeration_checkpoint_store_time_max` exists
3. if no checkpoint exists, do a full historical WASAPI enumeration for that collection
4. if a checkpoint exists, keep the current 30-day overlap-window behavior
5. after successful enumeration, save the max observed `store-time` as the checkpoint

That is the whole feature for this step.

---
## Why This Is the Right Next Step

1. **It directly matches Option 1**
   - first run does a full backfill
   - later runs stay incremental

2. **It is simple**
   - one checkpoint-based decision
   - no new workflow mode
   - no added operator action

3. **It matches the master plan**
   - the main plan already says first-run discovery behavior should be full historical backfill when no checkpoint exists

4. **It fits the existing code shape**
   - `main.py` stays thin
   - `lib/orchestration.py` remains the main production flow

---
## Specific Implementation Plan

### 1. Use the checkpoint as the mode switch

In `lib/orchestration.py`, keep the current per-collection flow, but make the mode explicit:

- load local state
- read `enumeration_checkpoint_store_time_max`
- if it is missing or `null`, treat the collection as **first run / full backfill**
- if it is present, treat the collection as **incremental / overlap-window run**

No more complex signal is needed for this step.

### 2. Compute the WASAPI boundary differently for the two modes

For **first run**:

- do not use `now - 30 days`
- instead, perform discovery with no effective historical cutoff, or with the simplest deliberately early cutoff already supported by the codebase

For **later runs**:

- keep the current behavior of using the checkpoint minus 30 days

The key point is:

- **no checkpoint = backfill everything**
- **checkpoint exists = normal recent overlap-window logic**

### 3. Keep downloading logic simple

Do not redesign download decision-making in this step.

For the Option-1 feature, the important behavior is:

- historical records become visible during first-run discovery
- the existing sequential flow then downloads files that are not already present locally

That is enough for this slice.

### 4. Save the checkpoint only after successful enumeration

Keep the existing checkpoint rule from the main plan:

- only write `enumeration_checkpoint_store_time_max` after WASAPI paging completes successfully
- write the max observed `store-time`

This ensures that once a collection finishes its first successful historical enumeration, later runs can switch to the normal overlap-window mode.

### 5. Log which mode was used

Add or adjust logging so it is obvious whether a collection ran in:

- `full-backfill-first-run` mode
- `incremental-overlap-window` mode

This will make behavior easy to verify during early production runs.

---
## Likely Code Touch Points

- `warc_tracker_script/lib/wasapi_discovery.py`
  - only if needed to support a no-cutoff or clearly early-cutoff discovery path
- `warc_tracker_script/lib/orchestration.py`
  - make the checkpoint-based mode decision explicit in the production flow
- `warc_tracker_script/tests/test_wasapi_discovery.py`
  - verify boundary computation behavior
- `warc_tracker_script/tests/test_orchestration.py`
  - verify first-run versus later-run orchestration behavior

Keep `warc_tracker_script/main.py` thin unless a tiny orchestration call adjustment is truly required.

---
## Minimum Test Coverage

Add focused `unittest` coverage for:

- no checkpoint => first-run full backfill behavior
- checkpoint present => 30-day overlap-window behavior
- successful first-run enumeration writes the checkpoint
- later runs continue using the checkpointed overlap-window path

The tests do not need to cover spreadsheet updates or Trio behavior for this step.

---
## Out of Scope for This Step

- spreadsheet write/update behavior
- Trio concurrency
- lock/cron wrapper hardening
- more advanced local file verification logic
- any new operator-facing bootstrap mode

---
## Success Criteria

- [ ] a collection with no `enumeration_checkpoint_store_time_max` is treated as first-run full backfill
- [ ] a collection with a checkpoint uses the existing 30-day overlap-window logic
- [ ] the checkpoint is written after successful historical enumeration
- [ ] the current sequential production flow remains the main execution path
- [ ] focused `unittest` coverage exists for first-run versus checkpointed behavior

---
## Likely Follow-Up After This Step

1. verify the feature on a small set of real collections
2. implement spreadsheet reporting from the sequential flow
3. later move toward the planned Trio architecture

---
## Handoff Notes

If you pick this up in a new session, re-read:

- `warc_tracker_script/AGENTS.md`
- `warc_tracker_script/PLAN__handling_historical_warcs.md`
- `warc_tracker_script/PLAN__simplified_warc_backup_script.md`
- `warc_tracker_script/PLAN__next_single_step.md`

Quick mental model:

- this step is only about the **simple checkpoint check**
- no checkpoint means **backfill everything**
- checkpoint present means **use the normal 30-day overlap window**
- keep the implementation small and inside the existing sequential orchestration
