# Next Single Step: Per-Collection Local State Management

## Context for Future Agents

**Code-Directives**: review `warc_tracker_script/AGENTS.md` for code-directives to follow.

**Project**: warc_tracker_script — A cron-triggered WARC backup + tracking-sheet update system

**Plan Reference**: `PLAN__warc_backup_script_v04.md` (the master plan)

**Current State**: Sheet ingestion is complete. The script can read Google Sheets and identify active collections.

---

## Goal of This Step

Implement the **per-collection local state file system** that supports idempotent operation, checkpointing, and recovery. This is the foundation for all subsequent pipeline stages (WASAPI querying, downloading, sheet updating).

---

## Why This Step First

1. **Downstream Dependency**: WASAPI discovery needs to know the `enumeration_watermark_store_time_max` to compute the 30-day overlap window
2. **Idempotency Requirement**: The script must survive interruptions without re-downloading files
3. **Recovery Semantics**: The local state (not the spreadsheet) is the source of truth for "what's already been processed"

---

## Requirements (from Master Plan)

### Directory Layout

```
{root}/_state/
  run-lock/
  collections/
    {collection_id}.json
  runs/
    {run_id}.json
```

### Per-Collection State Schema

Each `{collection_id}.json` must contain:

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | `str` | Timestamp-based identifier of last successful run (e.g., `20250305-143000-a1b2`) |
| `enumeration_watermark_store_time_max` | `str \| None` | ISO8601 timestamp of newest `store-time` observed from successful WASAPI enumeration |
| `last_successful_sheet_update_time` | `str \| None` | ISO8601 timestamp of last sheet update for this collection |
| `recent_window_filenames` | `list[str]` | Bounded list (max ~1000) of filenames in the lookback window for dedupe |
| `per_filename_status` | `dict[str, dict]` | Manifest of file attempts: `{filename: {"status": "downloaded\|failed\|missing", "last_attempt_at": "ISO8601", "error_count": int, "last_error_summary": str}}` |
| `failure_counters` | `dict` | Aggregate failure info for the collection |

### Key Behaviors

1. **Atomic Writes**: State updates must be atomic (write temp file → rename) to prevent corruption on interruption
2. **Graceful Missing State**: A collection with no state file is treated as "never processed"
3. **Watermark Advance Rules**:
   - Only advance `enumeration_watermark_store_time_max` after **successful full WASAPI pagination**
   - Download failures do NOT prevent watermark advance (they retry via overlap window + manifest)
   - Records missing `store-time` are integrity errors—do not use them to advance the watermark

### `run_id` Format

Use timestamp-based identifiers like `20250305-143000-a1b2` (YYYYMMDD-HHMMSS-random4):
- Enables audit trail correlation across logs, sheet updates, and state files
- Supports tracing which run last touched a collection

---

## Suggested Implementation Structure

Create `lib/collection_state.py` with:

```python
from dataclasses import dataclass

@dataclass
class CollectionState:
    """
    Represents the persisted state for a single collection.
    """
    run_id: str | None
    enumeration_watermark_store_time_max: str | None  # ISO8601
    last_successful_sheet_update_time: str | None  # ISO8601
    recent_window_filenames: list[str]
    per_filename_status: dict[str, FileStatusRecord]
    failure_counters: dict[str, int]

@dataclass
class FileStatusRecord:
    """
    Represents the status of a single file attempt.
    """
    status: str  # 'downloaded', 'failed', 'missing'
    last_attempt_at: str  # ISO8601
    error_count: int
    last_error_summary: str | None
```

And functions:

```python
def load_collection_state(state_root: Path, collection_id: int) -> CollectionState:
    """
    Loads state for a collection, returning default/empty state if file missing.
    """
    ...

def save_collection_state(
    state_root: Path,
    collection_id: int,
    state: CollectionState,
) -> None:
    """
    Atomically writes collection state to disk.
    """
    ...

def generate_run_id() -> str:
    """
    Generates a timestamp-based run identifier.
    """
    ...

def compute_query_after_datetime(
    watermark: str | None,
    lookback_days: int = 30,
) -> str:
    """
    Computes the 'after' datetime for WASAPI queries using overlap window.
    """
    ...
```

---

## Test Requirements

Create `tests/test_collection_state.py` covering:

1. **Happy path**: Load → modify → save → reload roundtrip
2. **Missing state**: Loading non-existent collection returns default/empty state
3. **Atomic write**: State file is either fully written or not present (no partial JSON)
4. **Watermark computation**: Correct ISO8601 datetime math with 30-day lookback
5. **Run ID format**: Valid timestamp + random suffix pattern
6. **Filename dedupe**: `recent_window_filenames` bounded list management

---

## Success Criteria

- [ ] `lib/collection_state.py` exists with `CollectionState` dataclass and load/save functions
- [ ] Atomic write implementation (temp file + rename)
- [ ] All functions have type hints and follow AGENTS.md conventions
- [ ] `tests/test_collection_state.py` exists with passing tests
- [ ] Can demonstrate: load state for collection → update watermark → save → reload shows new watermark

---

## Integration Note for Future Steps

Once this step is complete, the next step (WASAPI query wrapper) will:
1. Call `load_collection_state()` to get the current watermark
2. Use `compute_query_after_datetime()` to get the `store-time-after` parameter
3. After successful pagination, update `enumeration_watermark_store_time_max` and save

The downloader step will:
1. Check `per_filename_status` before downloading
2. Update status records after each attempt
3. Manage `recent_window_filenames` for dedupe

---

## Files to Create/Modify

**New files:**
- `lib/collection_state.py` — state management logic
- `tests/test_collection_state.py` — unit tests

**No modifications to existing files required** for this step.

---

## Appendix: Reference from Master Plan

From `PLAN__warc_backup_script_v04.md` Section "Local state management without a database":

> Per-collection state JSON should include:
> - `run_id` of last successful run (for cross-referencing)
> - last successful checkpoint (store-time/crawl-time)
> - last successful sheet update time
> - a record of recently downloaded filenames (bounded list)
> - failure counters / last error summary

From "How each run computes the query 'after' time":

> - Start with a reference watermark = `max(local_state.enumeration_watermark_store_time_max, sheet.last_wasapi_fetch)` if both exist.
> - Compute: `after_datetime = reference_watermark - lookback_window`.
