# Next Single Step: Production WASAPI Discovery with `store-time` Overlap

## Context for Future Agents

**Code-directives**: review `warc_tracker_script/AGENTS.md` before editing code.

**Master plan reference**: `warc_tracker_script/PLAN__simplified_warc_backup_script_v05.md`

**Current implementation status**:

- Spreadsheet ingestion is implemented in `warc_tracker_script/lib/collection_sheet.py`.
- Per-collection local state is implemented in `warc_tracker_script/lib/local_state.py`.
- The temporary investigative WASAPI metadata script exists in `warc_tracker_script/tmp_inspect_collection_wasapi.py`.
- `main.py` is still intentionally small and should remain thin.

**Important current code facts**:

- The production backup flow still does **not** have a WASAPI discovery module.
- The local-state module already persists `enumeration_checkpoint_store_time_max` and a filename-keyed `files` mapping.
- Tests use `unittest`.
- HTTP work must use `httpx`.

---
## Goal of This Step

Implement the first production version of **WASAPI discovery** for a single collection using:

- `store-time` as the only discovery clock
- the saved local checkpoint from `state.json`
- the required 30-day overlap window

This step should produce code and tests for a small library module that can:

- compute the `store-time-after` boundary from local state
- request paginated WASAPI results for one collection
- collect record metadata needed for later download decisions
- determine the maximum observed `store-time` from a successful enumeration
- leave checkpoint persistence decisions explicit for callers

This step should **not** yet implement actual WARC downloads.

---
## Why This Is the Right Next Step

1. **It directly follows the v05 implementation order**
   - Spreadsheet ingestion is done.
   - Local state is done.
   - Production WASAPI discovery is the next missing dependency.

2. **It unlocks later downloader work**
   - The downloader cannot decide what to fetch until discovery returns candidate WARC records.

3. **It keeps the architecture clean**
   - WASAPI logic belongs in `lib/` and can stay independent from `main.py`, Trio orchestration, and spreadsheet updates.

4. **It exercises the real checkpoint rule**
   - This is the first production step that actually uses the persisted local state as intended.

---
## In-Scope Deliverables

Implement a production discovery module, likely:

- `warc_tracker_script/lib/wasapi_discovery.py`

And add focused tests, likely:

- `warc_tracker_script/tests/test_wasapi_discovery.py`

The module should provide helpers for:

- computing the overlap-window query boundary
- parsing/validating relevant WASAPI record fields
- fetching paginated JSON for one collection
- extracting the maximum usable `store-time`

---
## Out of Scope for This Step

- No WARC payload downloads.
- No fixity generation.
- No local year/month path creation.
- No spreadsheet writes.
- No Trio concurrency.
- No broad orchestration rewrite in `main.py`.

---
## Required Behavior from the v05 Plan

### Query-boundary rule

For each collection:

1. read `enumeration_checkpoint_store_time_max` from local state
2. if missing, treat the run as a first run and use `now` as the reference point
3. compute `after_datetime = reference_checkpoint - 30 days`
4. query WASAPI with `store-time-after=<after_datetime>`

### Discovery clock rule

Use **only** `store-time` for checkpoint/discovery logic.

If a record is missing `store-time`:

- log it
- skip using it for checkpoint advancement
- continue processing other records

### Checkpoint advancement rule

This step should make it easy for callers to update the checkpoint only when:

- pagination completed successfully
- the updated local state is written durably

The module itself does not have to persist the checkpoint automatically, but its API should expose the information needed to do so correctly.

---
## Recommended API Shape

Keep the module small and testable. Illustrative function names:

```python
def compute_store_time_after_datetime(
    checkpoint_store_time_max: str | None,
    now: datetime,
    overlap_days: int = 30,
) -> datetime:
    ...


def format_wasapi_datetime(value: datetime) -> str:
    ...


def extract_discovery_records(page_payload: dict[str, object]) -> list[dict[str, object]]:
    ...


def extract_record_store_time(record: dict[str, object]) -> str | None:
    ...


def fetch_collection_discovery(
    client: httpx.Client,
    base_url: str,
    collection_id: int,
    after_datetime: datetime,
    page_size: int,
) -> dict[str, object]:
    ...
```

An alternative is to return a small result dataclass, for example with:

- discovered records
- request history
- completed-successfully flag
- max observed `store-time`

Either approach is fine if it stays simple.

---
## Data the Discovery Step Must Return

At minimum, the discovery result for one collection should make available:

- the collection id
- the query boundary actually used
- the records discovered across all pages
- the max observed usable `store-time`
- enough request/paging metadata to debug failures
- whether enumeration finished successfully

The records returned for later download-decision code should preserve fields such as:

- filename
- `store-time`
- file size if present
- source/download URL if present
- any record fields later steps may need for download and logging

Prefer preserving record payloads rather than aggressively narrowing them too early.

---
## HTTP / Paging Requirements

The module should:

- use `httpx`
- request WASAPI pages for a single collection
- include `store-time-after` in query params
- follow pagination until complete
- fail clearly on malformed responses or HTTP errors

Recommendation:

- keep retry behavior minimal in this step unless it falls out naturally
- record request URLs/params in returned debug metadata
- treat non-object JSON responses as errors

---
## Test Requirements

Add focused `unittest` coverage for the discovery helpers.

### Minimum tests to include

- **Query-boundary with checkpoint**
  - subtracts 30 days from a provided checkpoint

- **Query-boundary without checkpoint**
  - uses `now` as the reference point

- **Store-time extraction behavior**
  - valid `store-time` is returned
  - missing `store-time` returns `None`

- **Pagination happy path**
  - multiple mocked WASAPI pages are fetched and combined
  - max observed `store-time` is computed from the full successful enumeration

- **Missing `store-time` tolerance**
  - records without `store-time` do not break enumeration
  - they are excluded from checkpoint-max computation

- **Malformed response failure**
  - non-object JSON or structurally invalid page payload raises a clear error

### Reasonable mocking approach

Keep tests lightweight.

- Use a fake client object or `unittest.mock` to simulate `httpx.Client.get()`.
- Do not create live-network tests.

---
## Suggested Implementation Notes

- Put all production discovery logic in `lib/`, not in `main.py`.
- Keep the code independent from Google Sheets and downloader concerns.
- Reuse the existing local-state module by passing the saved checkpoint value into the discovery helper.
- Keep return values explicit enough that the later orchestrator can decide when to persist an updated checkpoint.

---
## Success Criteria

- [ ] a new production WASAPI discovery module exists under `lib/`
- [ ] the module computes `store-time-after` using the 30-day overlap rule
- [ ] the module fetches paginated WASAPI results for one collection
- [ ] the module tolerates records missing `store-time` while excluding them from checkpoint-max calculation
- [ ] the module returns the max usable `store-time` from successful enumeration
- [ ] focused `unittest` coverage exists for query-boundary, paging, and failure behavior

---
## Likely Follow-Up After This Step

After production WASAPI discovery is implemented and tested, the next step should likely be:

1. implement local year/month path building for collection WARC storage
2. define the download job shape from discovered WASAPI records
3. implement the downloader with temp-file then atomic rename

---
## Handoff Notes for the Next Agent / New Session

If you are picking this up in a new session, re-read:

- `warc_tracker_script/AGENTS.md`
- `warc_tracker_script/PLAN__simplified_warc_backup_script_v05.md`
- `warc_tracker_script/PLAN__next_single_step.md`
- `warc_tracker_script/OLD_PLAN__next_single_step.md`

Quick mental model of the codebase right now:

- `lib/collection_sheet.py` handles sheet ingestion.
- `lib/local_state.py` handles per-collection `state.json` persistence.
- `tmp_inspect_collection_wasapi.py` is investigative and should not be treated as the production discovery layer.
- `main.py` is still intentionally minimal.

The immediate objective is to add the smallest correct production WASAPI discovery layer that consumes the persisted local checkpoint and exposes clean results for later download logic.
