# Next Single Step: Implement Per-Collection Local `state.json` Management

## Context for Future Agents

**Code-directives**: review `warc_tracker_script/AGENTS.md` before editing code.

**Master plan reference**: `warc_tracker_script/PLAN__simplified_warc_backup_script_v05.md`

**Current implementation status**:

- Spreadsheet ingestion is already implemented in `warc_tracker_script/lib/collection_sheet.py`.
- The temporary WASAPI inspection script already exists in `warc_tracker_script/tmp_inspect_collection_wasapi.py`.
- Tests already exist for sheet parsing and the temporary WASAPI inspection helpers.
- `main.py` is still minimal and currently only loads active collection jobs from the spreadsheet.
- The next missing production building block in the v05 implementation sequence is per-collection local state.

**Important current code facts**:

- The project uses Python `3.12` per repository instructions.
- Use `unittest`, not `pytest`.
- Use single quotes and stay within `ruff.toml` line-length guidance.
- The local filesystem is the source of truth for the backup workflow.

---
## Goal of This Step

Implement the first production version of **per-collection local `state.json` handling** so later steps can rely on stable local checkpoint and retry state.

This step should create code and tests for a small library module that can:

- compute the per-collection state-file path
- create an in-memory default state structure when no file exists
- load existing `state.json` safely from disk
- write updated state atomically back to disk
- preserve the minimum fields required by the v05 plan

This step should **not** yet implement downloader logic or full WASAPI orchestration.

---
## Why This Is the Right Next Step

1. **It matches the v05 implementation order**
   - The plan sequence puts local `state.json` immediately after spreadsheet ingestion.
   - Spreadsheet ingestion is already done.

2. **It unlocks the next production steps cleanly**
   - WASAPI discovery needs a persisted checkpoint.
   - Retry and dedupe behavior need a persisted filename manifest.

3. **It keeps scope narrow but production-relevant**
   - This is a small, testable library step.
   - It avoids prematurely mixing filesystem state, networking, and concurrency into one change.

4. **It establishes the source-of-truth model early**
   - The v05 plan explicitly says the local filesystem is authoritative.
   - A stable state-file contract should exist before downloader and orchestrator code accumulate assumptions around it.

---
## In-Scope Deliverables

Implement a new production library module, likely something like:

- `warc_tracker_script/lib/local_state.py`

And add focused tests, likely something like:

- `warc_tracker_script/tests/test_local_state.py`

The module should provide helpers for:

- building the collection root path
- building the `state.json` path
- loading state from disk
- returning a default state when no file exists
- writing state atomically

---
## Out of Scope for This Step

- No WASAPI HTTP requests.
- No downloader implementation.
- No fixity hashing.
- No spreadsheet writes.
- No Trio concurrency.
- No lock/cron wrapper work.
- No end-to-end orchestration in `main.py` beyond, at most, tiny non-invasive integration if absolutely needed.

---
## Required State Shape for MVP

The state structure should stay minimal and aligned with the v05 plan.

At minimum, support:

- `enumeration_checkpoint_store_time_max`
- `files`

The `files` mapping should be keyed by filename and allow values such as:

- `status`
- `last_attempt_at`
- `error_count`
- optional short error summary

Recommendation for the initial default state:

```json
{
  "enumeration_checkpoint_store_time_max": null,
  "files": {}
}
```

Do not add extra schema complexity unless it is clearly needed for the next step.

---
## Storage/Layout Assumptions This Step Should Use

Use the v05 collection-local layout:

```text
{root}/collections/{collection_id}/
  warcs/
  fixity/
  state.json
```

Important:

- This step only needs to manage `state.json` paths and parent-directory creation.
- It does **not** need to create year/month subdirectories yet.
- It does **not** need to create WARC or fixity files yet.

---
## Behavioral Requirements

### Loading behavior

When loading state:

- if `state.json` does not exist, return the default state
- if `state.json` exists and contains valid JSON object data, return that data
- if `state.json` is malformed or not an object, fail clearly with a helpful exception

### Writing behavior

When saving state:

- ensure the collection directory exists
- write to a temporary file in the same directory
- atomically replace the target `state.json`
- produce stable, readable JSON formatting

### Data-shape behavior

For this step, keep validation practical rather than elaborate:

- require the top-level loaded payload to be a JSON object
- ensure missing top-level required keys are filled with defaults
- preserve existing file-manifest entries if present

Do not build a large custom validation framework yet.

---
## Recommended API Shape

Keep the API small and easy to test. Illustrative names:

```python
def build_collection_root_path(storage_root: Path, collection_id: int) -> Path:
    ...


def build_state_file_path(storage_root: Path, collection_id: int) -> Path:
    ...


def make_default_collection_state() -> dict[str, object]:
    ...


def load_collection_state(storage_root: Path, collection_id: int) -> dict[str, object]:
    ...


def save_collection_state(storage_root: Path, collection_id: int, state: dict[str, object]) -> Path:
    ...
```

These exact names are not mandatory, but the implementation should stay close to this level of simplicity.

---
## Test Expectations

Add focused `unittest` coverage for the new local-state helpers.

### Minimum tests to include

- **Default-load case**
  - loading state for a collection with no existing `state.json` returns the default structure

- **Round-trip save/load case**
  - saving a valid state and loading it again returns the expected content

- **Path-construction case**
  - the collection root and `state.json` paths match the v05 layout

- **Malformed JSON failure case**
  - an invalid `state.json` raises a clear error

- **Missing-key normalization case**
  - loading an older or partial JSON object fills in missing required top-level keys

### Nice-to-have test

- **Atomic-save sanity check**
  - saving state leaves a final `state.json` in place and does not leave the temp file behind

Use `tempfile.TemporaryDirectory()` or equivalent standard-library helpers rather than external test dependencies.

---
## Suggested Implementation Notes

- Keep the code in `lib/`, not in `main.py`.
- Prefer plain dict-based state for now rather than introducing dataclasses or pydantic-style schema code.
- Use `pathlib.Path` throughout.
- Keep functions top-level and individually testable.
- Make the smallest correct production abstraction that later WASAPI and downloader steps can call.

---
## Success Criteria

- [ ] a new production local-state module exists under `lib/`
- [ ] the module can compute collection-local `state.json` paths
- [ ] the module returns a default state when `state.json` is absent
- [ ] the module saves JSON atomically to `state.json`
- [ ] the module fails clearly on malformed state files
- [ ] focused `unittest` coverage exists for happy-path and edge-case behavior

---
## Likely Follow-Up After This Step

After local state is implemented and tested, the next step should be:

1. implement WASAPI discovery using `store-time`
2. read `enumeration_checkpoint_store_time_max`
3. apply the 30-day overlap window
4. enumerate candidate WARC records for download decisions

That follow-up will then have a stable persisted state layer to build on.

---
## Handoff Notes for the Next Agent / New Session

If you are picking this up in a new session, re-read:

- `warc_tracker_script/AGENTS.md`
- `warc_tracker_script/PLAN__simplified_warc_backup_script_v05.md`
- `warc_tracker_script/PLAN__next_single_step.md`

Quick mental model of the codebase right now:

- `lib/collection_sheet.py` is the main finished production module.
- `tmp_inspect_collection_wasapi.py` is an already-implemented investigative tool, not the next production milestone.
- `main.py` is intentionally small and should probably stay that way during this step.

The immediate objective is to add the smallest durable local-state layer that subsequent WASAPI and downloader work can trust.
