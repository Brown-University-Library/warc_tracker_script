# Next Single Step: Initial-Download Decision and Verification Slice

## Context for Future Agents

**Code-directives**: review `warc_tracker_script/AGENTS.md` before editing code.

**Master plan reference**: `warc_tracker_script/PLAN__simplified_warc_backup_script.md`

**User preference followed here**: build functionality sequentially from `warc_tracker_script/main.py` when possible, while keeping `main.py` thin and orchestration-focused.

**Current implementation status relevant to this step**:

- the sequential production flow in `main.py` and `lib/orchestration.py` already loads active collection jobs, runs WASAPI discovery, builds local paths, downloads missing files, writes fixity sidecars, updates `state.json`, and logs per-collection summaries
- the master plan’s first-run rule is already reflected in the codepath through `compute_store_time_after_datetime()` plus sequential orchestration
- what is still under-specified in production code is the plan rule for **determining what actually needs download** on an initial run and on later runs when a local file or sidecar already exists

---

## Goal of This Step

Implement the production decision layer that answers this question for each discovered WARC record:

**Should this record be downloaded now, skipped as already complete, or treated as needing local verification / repair work first?**

This step should make the current sequential pipeline correctly handle initial-download conditions described in the main plan:

- download when the local WARC does not exist
- re-process when the local WARC exists but expected sidecars are missing or invalid
- allow retry when the manifest records a prior failed attempt
- avoid re-downloading a file that is already complete and locally trustworthy

This is the most useful next step because it turns the current “download if destination file is absent” behavior into the fuller MVP rule set that the master plan already calls for.

---

## Why This Is the Right Next Step

1. **It closes a real gap between the plan and the code**
   - the plan says download need is based on file existence, size/fixity validity, and retry eligibility
   - the current sequential flow mostly skips when the destination WARC path already exists

2. **It strengthens first-run historical backfill correctness**
   - an initial run may encounter partially complete local state from interrupted manual testing or prior prototype runs
   - the script should classify those files deterministically instead of only treating them as “already exists”

3. **It preserves the preferred architecture**
   - `main.py` remains thin
   - the real logic stays in `lib/orchestration.py` plus small helper functions or a focused neighboring `lib/` module

4. **It de-risks later spreadsheet and Trio work**
   - once the download-decision contract is reliable, later progress reporting and worker concurrency can reuse it instead of mixing orchestration changes with correctness changes

---

## Specific Deliverable

Extend the current sequential production flow so that, before attempting any file transfer, each planned record is classified into one of these practical outcomes:

- needs full download
- has complete local WARC plus valid fixity sidecars and can be skipped
- has local WARC but missing or invalid fixity sidecars and needs local fixity regeneration
- has a prior failed manifest entry and should be retried
- cannot be trusted because required local verification failed and should be re-downloaded

The implementation should cover the MVP rules already stated in the master plan:

- local file missing => download needed
- local file exists but size verification fails => download needed
- SHA-256 sidecar missing or invalid => corrective action needed
- manifest says prior attempt failed and retry is allowed => download needed

Where the current codebase lacks one of the required verification signals, this step should add the smallest production-safe version needed for initial-download handling.

---

## Recommended Scope of the Change

### 1. Introduce an explicit local download-decision helper

Add a helper in `lib/orchestration.py` or a small dedicated `lib/` module that accepts:

- `CollectionJob` or `collection_id`
- the current manifest/state object
- one `PlannedDownload`

And returns a compact decision structure describing:

- `action`
  - `download`
  - `skip_complete`
  - `regenerate_fixity`
  - `redownload`
- `reason`
  - short, stable, loggable text
- any verification metadata needed for follow-up logging/reporting

This helper should become the authoritative gate for whether a file transfer is attempted.

### 2. Check local WARC completeness before skipping

Do not keep the current simple rule of:

- “if destination exists, skip”

Instead, inspect the local state of:

- WARC file path
- `.sha256` sidecar path
- `.json` sidecar path
- any manifest entry for the filename

For the first production slice, a pragmatic completeness rule is:

- if WARC exists and both sidecars exist and the manifest does not indicate failure, treat as complete enough to skip
- if WARC exists but one or both sidecars are missing, regenerate fixity sidecars without re-downloading unless another integrity signal says the WARC itself is untrustworthy
- if manifest says the last attempt failed and the WARC is absent, re-download
- if manifest says failure but a complete local WARC plus sidecars now exist, prefer local verification and normalize the manifest rather than blindly re-downloading

### 3. Add a minimum viable size/integrity check

The main plan says download is needed if local size verification fails.

Because the current orchestration appears not to persist authoritative remote expected size during planning, this step should choose the smallest clear implementation path:

- first inspect discovered WASAPI records for a usable size field already available in the record payload
- if available, thread that expected size into the planning/decision flow and compare against local file size
- if not available in a stable way, document that limitation in the new plan and implement the rest of the decision rules now, leaving explicit TODOs for authoritative remote-size comparison later

The key requirement is to avoid pretending size validation exists if the source data is not actually available.

### 4. Regenerate fixity when the WARC is already present

The current flow writes fixity only after a successful new download.

Extend it so that when a local WARC already exists but fixity artifacts are missing or unusable, the code can:

- skip network download
- compute SHA-256 over the existing WARC
- rewrite `.sha256` and `.json` sidecars atomically
- update the manifest to reflect a successful local fixity completion

This is particularly important for initial-download handling where a prior interrupted run may have left a valid WARC but incomplete sidecars.

### 5. Keep durable state updates aligned with the chosen action

For each decision branch, make sure `state.json` remains consistent:

- successful fresh download + fixity => manifest reflects success
- successful fixity regeneration on an already-present WARC => manifest reflects success and valid sidecar paths
- re-download failure => manifest reflects failure and increments retry/error information
- verified skip of a complete local file => manifest may remain unchanged unless normalization is needed

Do not introduce a large state-schema redesign in this step.

---

## Suggested Code Shape

- keep `main.py` unchanged except for orchestration wiring if absolutely necessary
- keep `lib/orchestration.py` as the production spine
- add small helper structures/functions for local verification and decision-making
- reuse existing `PlannedDownload`, `DownloadResult`, `FixityResult`, and manifest-update helpers where practical

A likely clean shape is:

- decision helper:
  - classifies each `PlannedDownload`
- execution helper:
  - performs download, skip, or fixity-regeneration based on that decision
- summary/logging helper:
  - reports how many files were downloaded, skipped-as-complete, repaired-via-fixity-regeneration, or failed

This keeps the current sequential flow intact while making the file-level behavior more correct.

---

## Minimum Test Coverage

Add focused `unittest` coverage for the decision rules and their execution effects.

Priority cases:

- discovered file with no local WARC => classified for download
- discovered file with local WARC and both sidecars present => classified as complete skip
- discovered file with local WARC but missing `.sha256` or `.json` => fixity regeneration path
- discovered file with manifest failure and no current WARC => retry download path
- discovered file with manifest failure but complete local artifacts present => normalize/skip or verify without network download
- local file exists with mismatched expected size, if expected size is available from discovery data => re-download path
- fixity regeneration success updates manifest correctly
- fixity regeneration failure updates manifest correctly and does not claim download success

Likely test files:

- `warc_tracker_script/tests/test_orchestration.py`
- possibly `warc_tracker_script/tests/test_fixity.py` if helper behavior needs extension
- possibly a new focused test module if the decision helper becomes large enough to deserve isolated tests

---

## Out of Scope for This Step

- spreadsheet start/progress/final reporting
- Trio concurrency and worker queues
- lock/cron wrapper hardening
- range-resume downloads
- major redesign of `state.json`
- non-WARC derivative handling

---

## Success Criteria

- [ ] the sequential orchestrator no longer treats “destination WARC exists” as the only skip rule
- [ ] a discovered WARC with complete local artifacts is skipped without network download
- [ ] a discovered WARC with existing file but missing/invalid sidecars triggers local fixity repair
- [ ] manifest-based retry behavior exists for prior failed downloads
- [ ] any implemented size verification is based on actual source metadata present in discovery records, not guesswork
- [ ] focused `unittest` coverage exists for the core initial-download decision branches

---

## Likely Follow-Up After This Step

1. implement spreadsheet reporting for start/final collection status from the sequential flow
2. add mid-download progress reporting once file-level correctness rules are stable
3. implement the Trio architecture with two download workers and one sheet updater

---

## Handoff Notes

If you pick this up in a new session, re-read:

- `warc_tracker_script/AGENTS.md`
- `warc_tracker_script/PLAN__simplified_warc_backup_script.md`
- `warc_tracker_script/PLAN__next_single_step.md`
- `warc_tracker_script/lib/orchestration.py`

Quick mental model:

- first-run historical enumeration is already in place
- the current remaining gap is file-level correctness for initial-download handling
- the next best production slice is to formalize download-vs-skip-vs-fixity-repair decisions in the existing sequential flow
- after that, spreadsheet reporting becomes easier because the orchestrator will have clearer per-file outcomes to summarize
