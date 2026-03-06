# Next Single Step: Durable Local Manifest Updates for Download and Fixity Outcomes

## Context for Future Agents

**Code-directives**: review `warc_tracker_script/AGENTS.md` before editing code.

**Master plan reference**: `warc_tracker_script/PLAN__simplified_warc_backup_script.md`

**User preference**: build functionality sequentially from `warc_tracker_script/main.py` when possible, while keeping `main.py` thin and orchestration-focused.

**Current implementation status**:

- `main.py` remains a thin entry point that loads config, configures logging, opens an authenticated `httpx.Client`, and iterates collection jobs.
- `lib/orchestration.py` processes collections sequentially.
- `lib/collection_sheet.py` loads active collection jobs from the spreadsheet.
- `lib/local_state.py` persists per-collection `state.json` atomically.
- `lib/wasapi_discovery.py` performs production WASAPI discovery with overlap-window checkpoint logic.
- `lib/storage_layout.py` derives year/month partitions from WARC filenames and computes planned WARC/fixity destinations.
- `lib/downloader.py` streams WARC files, writes to `*.partial`, removes stale partial files on retry, and atomically renames successful downloads into place.
- `lib/fixity.py` computes SHA-256 and writes `.sha256` and `.json` sidecars for successfully downloaded WARCs.
- The production flow now reaches actual local WARC download plus fixity creation, but it does not yet persist per-file manifest entries for download/fixity success or failure.

---
## Goal of This Step

Implement the first production version of **durable per-file local manifest updates** so the current sequential flow moves from “downloaded and fixity-written during this run” to “durably recorded file status in `state.json` for future retry/dedupe behavior.”

This step should add a small manifest/state layer that:

- records download success/failure per filename
- records fixity success/failure per filename
- records last-attempt timing for each processed file
- records a small amount of retry/error summary metadata
- writes the updated collection state durably through existing local-state helpers

This step should **not** yet implement spreadsheet writes or Trio concurrency.

---
## Why This Is the Right Next Step

1. **It directly follows the updated implementation sequence**
   - Discovery is done.
   - Path planning is done.
   - Downloading is done.
   - Fixity generation is done.
   - The next missing production behavior is durable manifest/state recording.

2. **It enables the project’s intended dedupe/retry model**
   - The master plan says retries and dedupe are manifest-based.
   - Without per-file state updates, the script cannot yet fully support that design.

3. **It fits the existing `main.py`-first flow**
   - `main.py` can remain thin.
   - `lib/orchestration.py` can update local state after download/fixity outcomes without introducing async structure yet.

4. **It preserves a small implementation increment**
   - Local manifest mutation can be validated before adding spreadsheet writes or Trio workers.

---
## In-Scope Deliverables

Update the local-state layer and orchestration flow so the current sequential production path can, for each planned download attempt:

- identify the filename being processed
- record successful download outcomes in `state['files'][filename]`
- record failed download outcomes in `state['files'][filename]`
- record fixity success/failure when fixity is attempted
- persist timestamps such as `last_attempt_at`
- persist a small retry/error summary such as `error_count` and `error_summary`
- save the updated state durably at an appropriate point in collection processing

And add focused tests, likely in:

- `warc_tracker_script/tests/test_local_state.py`
- `warc_tracker_script/tests/test_orchestration.py`

---
## Out of Scope for This Step

- No spreadsheet writes.
- No Trio concurrency.
- No redesign of `main.py`.
- No remote checksum comparison.
- No large schema redesign beyond what is needed for practical per-file manifest entries.

---
## Required Behavior from the Master Plan

### Manifest/state model

Per collection, `state.json` should be able to hold:

- `enumeration_checkpoint_store_time_max`
- `files` mapping keyed by filename

For each filename entry, the implementation should support values such as:

- `status`
- `last_attempt_at`
- `error_count`
- `error_summary`

For this step, it is acceptable to add a few explicit fields that make download/fixity results durable and easy to inspect, for example:

- download status/result fields
- fixity status/result fields
- source URL if useful
- stored local paths if useful

### Failure behavior

- a failed download should record a durable failed attempt
- a fixity failure after a successful download should also be recorded durably
- a successful WARC download should not be erased from disk just because fixity writing failed
- checkpoint advancement rules should remain as they are now; do not couple them to download/fixity success

---
## Recommended API Shape

Keep the change small and explicit. Illustrative directions:

```python
def build_file_manifest_entry(...) -> dict[str, object]:
    ...


def update_file_manifest_entry(
    state: dict[str, object],
    filename: str,
    ...
) -> dict[str, object]:
    ...
```

Exact naming can vary if the interface stays simple and testable.

It is also acceptable to keep the helper layer minimal and have `lib/orchestration.py` call a small number of top-level local-state helpers.

---
## Orchestration Integration Requirement

Extend the current sequential flow in `lib/orchestration.py` so that after a planned file is processed it can:

1. determine whether download succeeded or failed
2. determine whether fixity succeeded or failed when attempted
3. update `state['files'][filename]` with durable per-file outcome data
4. save the collection state durably
5. preserve the existing thin `main.py` approach

Do this without introducing spreadsheet abstractions or Trio worker structure yet.

---
## Test Requirements

Add focused `unittest` coverage.

### Minimum tests to include

- **Manifest entry happy path after successful download and fixity**
  - state contains a filename entry marked as successfully processed

- **Download failure recording**
  - failed download increments or records error metadata and durable failed status

- **Fixity failure recording**
  - successful download plus failed fixity records the partial-success state clearly

- **State persistence integration**
  - orchestration saves updated collection state after processing outcomes

- **Existing checkpoint behavior remains intact**
  - checkpoint save logic for successful/incomplete discovery still behaves as before

Keep tests local and mocked where appropriate; do not add live network tests.

---
## Suggested Implementation Notes

- Keep `main.py` thin.
- Prefer small helper functions in `lib/local_state.py` or another small `lib/` helper module rather than embedding all manifest logic inline.
- Use UTC ISO-8601 timestamps.
- Keep the manifest schema explicit but small.
- Match repository style from `AGENTS.md` and `ruff.toml`.
- Make the state updates durable with the existing atomic-save approach.

---
## Success Criteria

- [ ] per-file manifest entries are written to `state.json`
- [ ] successful downloads are recorded durably
- [ ] failed downloads are recorded durably
- [ ] fixity failures are recorded durably
- [ ] orchestration persists updated collection state after file processing
- [ ] focused `unittest` coverage exists for happy-path and failure-path manifest recording

---
## Likely Follow-Up After This Step

After durable local manifest updates are implemented, the next step should likely be:

1. implement spreadsheet write/update behavior
2. then decide whether Trio worker structure or operational hardening should come next

---
## Handoff Notes for the Next Agent / New Session

If you are picking this up in a new session, re-read:

- `warc_tracker_script/AGENTS.md`
- `warc_tracker_script/PLAN__simplified_warc_backup_script.md`
- `warc_tracker_script/PLAN__next_single_step.md`

Quick mental model of the codebase right now:

- `main.py` is a thin entry point and should stay that way.
- `lib/orchestration.py` is the current sequential production flow.
- `lib/wasapi_discovery.py` returns discovered records and checkpoint info.
- `lib/storage_layout.py` maps discovered filenames to deterministic WARC and fixity destinations.
- `lib/downloader.py` performs the safe local WARC write path.
- `lib/fixity.py` performs SHA-256 and sidecar generation.
- `lib/local_state.py` can already load and save collection state atomically, but it does not yet manage durable per-file outcome entries beyond the top-level checkpoint structure.

The immediate objective is to add the smallest correct manifest/state update layer that plugs into the existing sequential orchestration flow and durably records per-file download and fixity outcomes for future retry/dedupe behavior.
