# Next Single Step: SHA-256 and Fixity Sidecar Writing

## Context for Future Agents

**Code-directives**: review `warc_tracker_script/AGENTS.md` before editing code.

**Master plan reference**: `warc_tracker_script/PLAN__simplified_warc_backup_script.md`

**User preference**: build functionality sequentially from `warc_tracker_script/main.py` when possible, while keeping `main.py` thin and orchestration-focused.

**Current implementation status**:

- `main.py` remains a thin entry point that loads config, configures logging, opens an authenticated `httpx.Client`, and iterates collection jobs.
- `lib/orchestration.py` processes collections sequentially.
- `lib/collection_sheet.py` loads active collection jobs from the spreadsheet.
- `lib/local_state.py` persists per-collection `state.json`.
- `lib/wasapi_discovery.py` performs production WASAPI discovery with overlap-window checkpoint logic.
- `lib/storage_layout.py` derives year/month partitions from WARC filenames and computes planned WARC/fixity destinations.
- `lib/downloader.py` streams WARC files, writes to `*.partial`, removes stale partial files on retry, and atomically renames successful downloads into place.
- The production flow now reaches actual local WARC download, but it does not yet compute SHA-256 or write fixity sidecars.

---
## Goal of This Step

Implement the first production version of **fixity generation** so the current sequential flow moves from “downloaded local WARC file” to “downloaded WARC plus local SHA-256 artifacts.”

This step should add a small fixity layer that:

- computes SHA-256 for a successfully downloaded WARC file
- writes a `{filename}.sha256` sidecar using standard checksum-line format
- writes a lightweight `{filename}.json` metadata sidecar
- returns explicit success/failure information to the caller

This step should **not** yet update the durable manifest or spreadsheet state.

---
## Why This Is the Right Next Step

1. **It directly follows the updated implementation sequence**
   - Discovery is done.
   - Path planning is done.
   - Downloading is done.
   - The next missing production behavior is fixity creation.

2. **It fits the existing `main.py`-first flow**
   - `main.py` can remain thin.
   - `lib/orchestration.py` can call a fixity helper after successful download, without introducing Trio yet.

3. **It preserves a small implementation increment**
   - Fixity can be validated before adding manifest mutation, spreadsheet writes, or async worker structure.

4. **It reduces risk in the right order**
   - Local checksum computation and sidecar writing are core integrity features.
   - It is better to validate those artifacts before layering in broader state updates.

---
## In-Scope Deliverables

Implement a small production fixity module, likely one of:

- `warc_tracker_script/lib/fixity.py`
- or `warc_tracker_script/lib/sha256_sidecar.py`

And add focused tests, likely one of:

- `warc_tracker_script/tests/test_fixity.py`

Update the current sequential orchestration flow so it can, for successful downloads:

- identify the downloaded WARC path
- identify the planned fixity sidecar paths
- compute SHA-256 for the downloaded file
- write `.sha256` and `.json` sidecars
- log fixity success or failure clearly

---
## Out of Scope for This Step

- No durable manifest success/failure recording yet.
- No spreadsheet writes.
- No Trio concurrency.
- No broad redesign of `main.py`.
- No remote checksum comparison.

---
## Required Behavior from the Master Plan

### Fixity artifacts

For each downloaded WARC:

1. compute **SHA-256**
2. write `{filename}.sha256` with standard checksum-line format
3. write `{filename}.json` with lightweight metadata:
   - sha256
   - size
   - source URL
   - relevant timestamps

### Storage behavior

- use the already-planned sidecar paths from `lib/storage_layout.py`
- create parent directories as needed
- do not add BagIt, OCFL, or remote verification in this step

### Failure behavior

- if fixity writing fails, log the failure clearly
- do not delete a successfully downloaded WARC just because sidecar writing failed
- avoid leaving misleading partial sidecar content behind when practical

---
## Recommended API Shape

Keep the module small and explicit. Illustrative shapes:

```python
@dataclass(frozen=True)
class FixityResult:
    success: bool
    warc_path: Path
    sha256_path: Path
    json_path: Path
    sha256_hexdigest: str | None
    size: int
    error_message: str | None


def compute_sha256_for_file(file_path: Path, chunk_size: int = 65536) -> str:
    ...


def write_fixity_sidecars(
    warc_path: Path,
    sha256_path: Path,
    json_path: Path,
    source_url: str,
) -> FixityResult:
    ...
```

Exact naming can vary if the interface stays simple and testable.

---
## Orchestration Integration Requirement

Extend the current sequential flow in `lib/orchestration.py` so that after a successful download it can:

1. inspect the planned fixity paths for that filename
2. call the fixity helper
3. log per-file fixity success/failure
4. include fixity outcomes in the collection-level summary log if helpful

Do this without turning `main.py` into a logic-heavy script.

If necessary, keep orchestration limited to a small, direct call path rather than introducing manifest abstractions yet.

---
## Test Requirements

Add focused `unittest` coverage.

### Minimum tests to include

- **SHA-256 computation happy path**
  - a known file content produces the expected hexdigest

- **Checksum sidecar writing**
  - `{filename}.sha256` is written with standard checksum-line format

- **JSON sidecar writing**
  - `{filename}.json` contains sha256, size, source URL, and timestamps or equivalent relevant metadata used by the implementation

- **Fixity failure behavior**
  - sidecar-writing failure returns or records a clear error
  - the downloaded WARC file remains in place

- **Orchestration consumption**
  - the sequential orchestration invokes fixity generation after a successful download
  - failed downloads do not attempt fixity generation

Keep tests local and mocked where appropriate; do not add live network tests.

---
## Suggested Implementation Notes

- Keep fixity logic in `lib/`, not in `main.py`.
- Use `pathlib.Path` throughout.
- Prefer chunked hashing over reading the whole file into memory.
- Use atomic replace for sidecar writes if practical.
- Match repository style from `AGENTS.md` and `ruff.toml`.
- Keep return values explicit enough that later steps can add manifest updates without redesigning the fixity layer.

---
## Success Criteria

- [ ] a production fixity module exists under `lib/`
- [ ] SHA-256 is computed for downloaded WARC files
- [ ] `.sha256` sidecars are written in checksum-line format
- [ ] `.json` metadata sidecars are written with lightweight fixity metadata
- [ ] the sequential orchestration flow invokes fixity generation after successful downloads
- [ ] failed downloads do not attempt fixity generation
- [ ] focused `unittest` coverage exists for happy-path, failure, and orchestration behavior

---
## Likely Follow-Up After This Step

After fixity writing is implemented and integrated, the next step should likely be:

1. update local manifest entries for download and fixity success/failure
2. then decide whether spreadsheet updates or Trio worker structure should come next

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
- `lib/storage_layout.py` maps discovered filenames to deterministic WARC and fixity destinations.
- `lib/downloader.py` now performs the safe local WARC write path.
- The next missing production dependency is SHA-256 and sidecar generation for successfully downloaded files.

The immediate objective is to add the smallest correct fixity layer that plugs into the existing sequential orchestration flow and writes `.sha256` plus `.json` artifacts safely for downloaded WARC files.

---
