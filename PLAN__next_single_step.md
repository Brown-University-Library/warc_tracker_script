# Next Single Step: Per-Collection Local State Management

## Context for Future Agents

**Code-directives**: review `warc_tracker_script/AGENTS.md` before editing code.

**Master plan reference**: `warc_tracker_script/PLAN__warc_backup_script_v04.md`

**Current implementation status**:

- Sheet ingestion is already implemented in `warc_tracker_script/lib/collection_sheet.py`.
- The manager/orchestrator is currently minimal in `warc_tracker_script/main.py`.
- `main.py` currently does only three things:
  - loads `.env`
  - validates `GSHEET_SPREADSHEET_ID`
  - calls `fetch_collection_jobs(spreadsheet_id)` and logs the active collection count

**Important current code facts**:

- `lib/collection_sheet.py` already defines `CollectionJob` as the canonical collection-level work unit.
- Header-row detection and active-row filtering are already working.
- The project uses Python `3.12` per `pyproject.toml`.
- Tests should use `unittest`, not `pytest`.
- `ruff.toml` uses single quotes and a max line length of `125`.

---
## Goal of This Step

Implement the **per-collection local state layer** that supports:

- idempotent operation
- watermark/checkpoint persistence
- per-file retry tracking
- safe recovery after interruption

This is the next correct dependency for WASAPI discovery, downloading, and sheet-update orchestration.

---
## Why This Is the Right Next Step

1. **WASAPI enumeration depends on it**
   - The next phase needs a persisted `enumeration_watermark_store_time_max` to compute the overlap-window query boundary.

2. **Local state is the operational source of truth**
   - The master plan explicitly treats the spreadsheet as reporting/control, not correctness-critical state.

3. **It keeps `main.py` thin**
   - This repository already has a manager-style `main.py`; adding state logic in `lib/collection_state.py` fits the existing structure.

---
## Scope Boundaries for This Step

### In scope

- Create the collection-state module.
- Define the persisted schema and serialization/deserialization behavior.
- Implement atomic load/save helpers.
- Implement `run_id` generation.
- Implement helper logic for overlap-window date calculation.
- Add focused unit tests.

### Out of scope

- No WASAPI HTTP client yet.
- No download logic yet.
- No sheet writes yet.
- No concurrency/Trio work yet.
- No broad refactor of `main.py` unless a very small integration hook is genuinely useful.

---
## Requirements from the Master Plan

### Directory layout

```text
{root}/_state/
  run-lock/
  collections/
    {collection_id}.json
  runs/
    {run_id}.json
```

For this step, the required deliverable is the `collections/{collection_id}.json` portion.
The `runs/{run_id}.json` file can remain deferred unless it falls out naturally from the implementation.

### Required per-collection state fields

Each `{collection_id}.json` should persist at least:

| Field | Type | Notes |
|---|---|---|
| `run_id` | `str | None` | Last run to persist meaningful state for this collection |
| `enumeration_watermark_store_time_max` | `str | None` | ISO8601 timestamp for newest `store-time` from successful full enumeration |
| `last_successful_sheet_update_time` | `str | None` | ISO8601 timestamp |
| `recent_window_filenames` | `list[str]` | Bounded dedupe list for lookback-window overlap |
| `per_filename_status` | `dict[str, dict]` | Manifest keyed by filename |
| `failure_counters` | `dict[str, int]` | Aggregate counters |

### File-status manifest shape

Recommended per-filename record:

| Field | Type | Notes |
|---|---|---|
| `status` | `str` | Start with `downloaded`, `failed`, or `missing` |
| `last_attempt_at` | `str | None` | ISO8601 timestamp |
| `error_count` | `int` | Increment on failed attempts |
| `last_error_summary` | `str | None` | Short text only |

---
## Behavioral Requirements

1. **Atomic writes**
   - Write to a temp file in the destination directory, then rename atomically.
   - A crash/interruption must not leave a truncated JSON state file in place.

2. **Graceful missing state**
   - If a collection has no file yet, loading should return a valid default state object.

3. **Stable serialization**
   - JSON output should be deterministic enough for inspection and debugging.
   - Use a consistent field layout/order if practical.

4. **Watermark semantics**
   - The module should support the master-plan rule that watermark advancement happens only after successful full WASAPI enumeration.
   - This module does not need to enforce the whole WASAPI workflow yet, but it should make the correct usage obvious.

5. **Fresh-run utility**
   - A helper for generating a timestamp-based `run_id` should exist in this step because later stages will need it immediately.

---
## Recommended Implementation Structure

Create `warc_tracker_script/lib/collection_state.py`.

Recommended dataclasses:

```python
@dataclass
class FileStatusRecord:
    """
    Represents the persisted status for a single filename.
    """

@dataclass
class CollectionState:
    """
    Represents persisted per-collection state.
    """
```

Recommended functions:

```python
def build_state_root_path(warc_backup_root: Path) -> Path:
    ...

def get_collection_state_path(state_root: Path, collection_id: int) -> Path:
    ...

def load_collection_state(state_root: Path, collection_id: int) -> CollectionState:
    ...

def save_collection_state(state_root: Path, collection_id: int, state: CollectionState) -> None:
    ...

def generate_run_id(now: datetime | None = None) -> str:
    ...

def compute_query_after_datetime(
    reference_watermark: datetime | None,
    lookback_days: int = 30,
    now: datetime | None = None,
) -> datetime:
    ...
```

Also recommended helper functions:

```python
def collection_state_to_dict(state: CollectionState) -> dict[str, object]:
    ...

def collection_state_from_dict(data: dict[str, object]) -> CollectionState:
    ...

def trim_recent_window_filenames(filenames: list[str], max_items: int = 1000) -> list[str]:
    ...
```

Notes:

- Prefer `datetime` objects internally where possible, and serialize as ISO8601 strings at the file boundary.
- Keeping serialization helpers explicit will make future schema evolution easier.
- Keep the module independent from Google Sheets and HTTP code.

---
## Specific Design Recommendations

### State-root decision

A likely clean design is:

- main backup root comes later from `WARC_BACKUP_ROOT`
- state root is derived as `{WARC_BACKUP_ROOT}/_state`

If the backup-root configuration is not implemented yet, it is acceptable in this step to keep the collection-state module path-based and let callers provide `state_root: Path` directly.

Recommendation: **do not hard-wire environment-variable reads into `lib/collection_state.py`**. Keep the module pure and caller-driven.

### Timestamp handling

Recommendation:

- store timestamps in ISO8601 form
- prefer timezone-aware UTC datetimes in code
- avoid mixing naive and aware datetimes

### Corrupt JSON handling

Recommendation:

- if a state file exists but contains invalid JSON, raise a clear exception rather than silently resetting state
- include the collection id/path in the error message

This is safer for preservation work than silently discarding state.

### Bounded filename window

Recommendation:

- keep `recent_window_filenames` insertion-ordered
- trim to a fixed max size
- preserve newest entries when trimming

A plain `list[str]` is fine for persistence at this stage.

---
## Test Requirements

Create `warc_tracker_script/tests/test_collection_state.py` using `unittest`.

Cover at least:

1. **Roundtrip persistence**
   - load default state
   - modify fields
   - save
   - reload
   - confirm values persist

2. **Missing file behavior**
   - loading a non-existent collection returns a default `CollectionState`

3. **Atomic write outcome**
   - after save, the final JSON file exists and is valid JSON
   - no `.tmp` / partial artifact remains

4. **Run-id format**
   - matches `YYYYMMDD-HHMMSS-xxxx` where suffix is short random lowercase hex or similar

5. **Query-after computation**
   - watermark present: subtracts `lookback_days`
   - watermark absent: uses `now`

6. **Filename-window trimming**
   - trimming preserves newest entries and respects max size

7. **Invalid JSON failure**
   - malformed persisted JSON raises a clear exception

If implementation uses helper serialization functions, test those indirectly through load/save unless a direct unit test adds real value.

---
## Suggested Minimal Integration

This step does **not** require meaningful orchestration changes in `main.py`.

However, one small optional improvement would be acceptable:

- add a temporary local demonstration path in tests only
- or add a tiny, non-default smoke helper later when the WASAPI step begins

Recommendation: keep this step focused on the library module + tests.

---
## Success Criteria

- [ ] `warc_tracker_script/lib/collection_state.py` exists
- [ ] `CollectionState` and `FileStatusRecord` dataclasses exist
- [ ] default-load behavior works when no state file exists
- [ ] atomic save behavior exists
- [ ] `generate_run_id()` exists and is tested
- [ ] `compute_query_after_datetime()` exists and is tested
- [ ] `warc_tracker_script/tests/test_collection_state.py` exists
- [ ] tests pass via `uv run ./run_tests.py` or an equivalent repo-approved unittest invocation

---
## Handoff Notes for the Next Agent / New Session

If you are picking this up in a new session, start by re-reading:

- `warc_tracker_script/AGENTS.md`
- `warc_tracker_script/PLAN__warc_backup_script_v04.md`
- `warc_tracker_script/main.py`
- `warc_tracker_script/lib/collection_sheet.py`
- `warc_tracker_script/PLAN__next_single_step.md`

Quick mental model of the codebase right now:

- `main.py` is the manager/orchestrator entry point and is intentionally very small.
- `lib/collection_sheet.py` is the first completed library module and is a good style/template reference.
- The project is still in early pipeline-building mode; there is not yet a WASAPI client, downloader, or state module.

The next implementation should preserve these architectural directions:

- keep `main.py` thin
- put domain logic in `lib/`
- keep new code independently testable
- avoid prematurely coupling state code to Google Sheets or HTTP concerns

Likely next step after this one is complete:

- implement the WASAPI query wrapper that consumes `CollectionState`
- use the saved watermark to compute `store-time-after`
- update and persist watermark only after successful full pagination

---
## Appendix: Direct References from the Master Plan

From the master plan's local-state section:

> Per-collection state JSON should include:
> - `run_id` of last successful run (for cross-referencing)
> - last successful checkpoint (store-time/crawl-time)
> - last successful sheet update time
> - a record of recently downloaded filenames (bounded list)
> - failure counters / last error summary

From the master plan's query-boundary section:

> Start with a reference watermark = `max(local_state.enumeration_watermark_store_time_max, sheet.last_wasapi_fetch)` if both exist.
> Compute: `after_datetime = reference_watermark - lookback_window`.
