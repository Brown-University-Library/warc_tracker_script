# Next Single Step: Local WARC and Fixity Path Building

## Context for Future Agents

**Code-directives**: review `warc_tracker_script/AGENTS.md` before editing code.

**Master plan reference**: `warc_tracker_script/PLAN__simplified_warc_backup_script.md`

**User preference**: build functionality sequentially from `warc_tracker_script/main.py` when possible, while keeping `main.py` thin and orchestration-focused.

**Current implementation status**:

- `main.py` loads config, configures logging, opens an authenticated `httpx.Client`, and iterates collection jobs.
- `lib/orchestration.py` processes each collection sequentially.
- `lib/collection_sheet.py` loads active collection jobs from the spreadsheet.
- `lib/local_state.py` persists per-collection `state.json`.
- `lib/wasapi_discovery.py` performs production WASAPI discovery with the overlap-window checkpoint logic.
- The current production flow now stops after discovery, checkpoint persistence, and logging pending download candidates.

---
## Goal of This Step

Implement the first production version of **local WARC/fixity path building** so the existing sequential orchestration flow can move from “discovered record” to “concrete planned local destination.”

This step should add a small path-building layer that:

- derives year/month partitions from WARC filenames
- computes the final WARC destination path
- computes companion fixity file paths
- gives the orchestrator enough structured information to log or stage future download work

This step should **not** yet download files or write fixity content.

---
## Why This Is the Right Next Step

1. **It directly follows the current implementation sequence**
   - Discovery is already implemented.
   - The next missing dependency before download work is destination-path computation.

2. **It fits the existing `main.py`-first flow**
   - `main.py` can stay unchanged or nearly unchanged.
   - `lib/orchestration.py` can call a new helper immediately after discovery.

3. **It keeps the next downloader step small**
   - Once each record has a resolved destination, the downloader only needs to stream to `*.partial`, rename, and record results.

4. **It validates the storage-layout decision now**
   - The plan already locks in the collection/year/month structure.
   - This is the smallest production step that makes that design real.

---
## In-Scope Deliverables

Implement a small production module, likely one of:

- `warc_tracker_script/lib/storage_layout.py`
- or `warc_tracker_script/lib/download_paths.py`

And add focused tests, likely one of:

- `warc_tracker_script/tests/test_storage_layout.py`
- or `warc_tracker_script/tests/test_download_paths.py`

Update the current sequential orchestration flow so that, for each discovered candidate record with a usable filename, it can compute and log the planned local destination paths.

---
## Out of Scope for This Step

- No file downloads.
- No `*.partial` writing yet.
- No SHA-256 calculation.
- No fixity file contents.
- No spreadsheet writes.
- No Trio concurrency.
- No broad redesign of `main.py`.

---
## Required Behavior from the Master Plan

### Local storage layout

Use this layout:

```text
{root}/collections/{collection_id}/
  warcs/
    {yyyy}/
      {mm}/
        {filename}
  fixity/
    {yyyy}/
      {mm}/
        {filename}.sha256
        {filename}.json
  state.json
```

### Partitioning rule

- derive `{yyyy}` and `{mm}` from the WARC filename timestamp
- keep the rule simple and deterministic
- if the filename does not contain a usable timestamp, fail clearly so the caller can log and skip it

### Scope rule

- handle only WARC-oriented production paths for now
- do not add crawl-specific or extra sharding rules

---
## Recommended API Shape

Keep the module small and explicit. Illustrative shapes:

```python
def extract_warc_timestamp_parts(filename: str) -> tuple[str, str]:
    ...


def build_collection_storage_root(storage_root: Path, collection_id: int) -> Path:
    ...


def build_warc_destination_path(storage_root: Path, collection_id: int, filename: str) -> Path:
    ...


def build_fixity_paths(storage_root: Path, collection_id: int, filename: str) -> tuple[Path, Path]:
    ...
```

An alternative is a small dataclass, for example:

- `warc_path`
- `sha256_path`
- `json_path`
- `year`
- `month`

Either approach is fine if it stays simple and testable.

---
## Orchestration Integration Requirement

Extend the current sequential flow in `lib/orchestration.py` so that after discovery it can:

1. inspect candidate records
2. extract usable filenames
3. compute planned destination paths
4. log enough detail to confirm the path-building behavior works

Do this without turning `main.py` into a logic-heavy script.

---
## Test Requirements

Add focused `unittest` coverage.

### Minimum tests to include

- **Timestamp extraction happy path**
  - a valid WARC filename yields the expected year/month

- **WARC destination path building**
  - the expected collection/year/month file path is returned

- **Fixity path building**
  - both `.sha256` and `.json` sidecar paths are returned in the fixity tree

- **Invalid filename handling**
  - a filename without a parseable timestamp raises a clear error

- **Orchestration consumption**
  - the current sequential orchestration can consume discovered records and compute planned paths without starting downloads

---
## Suggested Implementation Notes

- Keep path-building logic in `lib/`, not in `main.py`.
- Keep helper functions pure where possible.
- Use `pathlib.Path` throughout.
- Match repository style from `AGENTS.md` and `ruff.toml`.
- Prefer returning structured data rather than ad hoc string concatenation.

---
## Success Criteria

- [ ] a production storage/path helper module exists under `lib/`
- [ ] the helper derives year/month from WARC filenames
- [ ] the helper returns the correct WARC destination path for a collection
- [ ] the helper returns matching fixity sidecar paths
- [ ] invalid filenames fail clearly
- [ ] the current sequential orchestration flow consumes the helper without adding download behavior yet
- [ ] focused `unittest` coverage exists for path parsing/building behavior

---
## Likely Follow-Up After This Step

After local path building is implemented and integrated, the next step should likely be:

1. implement the downloader with `*.partial` then atomic rename
2. add SHA-256 calculation and sidecar writing
3. update local manifest entries for download success/failure

---
## Handoff Notes for the Next Agent / New Session

If you are picking this up in a new session, re-read:

- `warc_tracker_script/AGENTS.md`
- `warc_tracker_script/PLAN__simplified_warc_backup_script.md`
- `warc_tracker_script/PLAN__next_single_step.md`

Quick mental model of the codebase right now:

- `main.py` is a thin entry point and should stay that way.
- `lib/orchestration.py` is the current sequential production flow.
- `lib/wasapi_discovery.py` already returns discovered records and checkpoint info.
- The next missing production dependency before download implementation is deterministic local destination-path construction.

The immediate objective is to add the smallest correct path-building layer that plugs into the existing sequential orchestration flow and prepares for downloader work.

---
