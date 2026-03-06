# Next Single Step: Local WARC and Fixity Path Building

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
- `lib/storage_layout.py` now derives year/month partitions from WARC filenames and computes planned WARC/fixity destinations.
- The production flow currently stops after discovery, checkpoint persistence, planned-path computation, and logging.

---
## Goal of This Step

Implement the first production version of the **downloader** so the existing sequential orchestration flow can move from “planned local destination” to “actual downloaded local WARC file.”

This step should add a small download layer that:

- streams a WARC from Archive-It using `httpx`
- writes to a `*.partial` file first
- replaces the final destination atomically on success
- removes or overwrites stale partial files on retry
- returns explicit success/failure information to the caller

This step should **not** yet compute SHA-256 sidecars or update spreadsheet state.

---
## Why This Is the Right Next Step

1. **It directly follows the updated implementation sequence**
   - Discovery is done.
   - Path planning is done.
   - The next missing production behavior is the actual download write path.

2. **It fits the existing `main.py`-first flow**
   - `main.py` can remain thin.
   - `lib/orchestration.py` can call a download helper after path planning, without introducing Trio yet.

3. **It preserves a small implementation increment**
   - Downloading can be validated before adding fixity, manifest mutation, or async worker structure.

4. **It reduces risk in the right order**
   - Correct temp-file and atomic-rename behavior is a core filesystem safety concern.
   - It is better to validate that before layering in checksums and sheet updates.

---
## In-Scope Deliverables

Implement a small production download module, likely one of:

- `warc_tracker_script/lib/downloader.py`
- or `warc_tracker_script/lib/warc_downloader.py`

And add focused tests, likely one of:

- `warc_tracker_script/tests/test_downloader.py`

Update the current sequential orchestration flow so it can, for a small set of valid discovered records:

- identify a usable source URL
- identify the planned local WARC destination path
- invoke the downloader helper
- log download success or failure clearly

---
## Out of Scope for This Step

- No SHA-256 calculation yet.
- No `.sha256` or `.json` sidecar writing yet.
- No durable manifest success/failure recording yet.
- No spreadsheet writes.
- No Trio concurrency.
- No broad redesign of `main.py`.

---
## Required Behavior from the Master Plan

### HTTP behavior

Use `httpx` with:

- streaming download
- reasonable timeout values
- clear failure behavior on HTTP/network errors

Retry logic can remain minimal in this step if needed.

### File-write behavior

For MVP download handling:

1. download to `*.partial`
2. on success, rename atomically to the final filename
3. if interrupted or retried, stale partial files should not corrupt the final target

Do not implement HTTP range-resume in this step.

### Storage behavior

- use the already-planned destination path from `lib/storage_layout.py`
- create parent directories as needed
- do not write fixity artifacts yet

---
## Recommended API Shape

Keep the module small and explicit. Illustrative shapes:

```python
@dataclass(frozen=True)
class DownloadResult:
    success: bool
    destination_path: Path
    partial_path: Path
    bytes_written: int
    source_url: str
    error_message: str | None


def build_partial_download_path(destination_path: Path) -> Path:
    ...


def download_to_path(
    client: httpx.Client,
    source_url: str,
    destination_path: Path,
    chunk_size: int = 65536,
) -> DownloadResult:
    ...
```

Exact naming can vary if the interface stays simple and testable.

---
## Source-URL Handling Requirement

The orchestration layer should only attempt a download when a discovered record exposes a usable source URL.

For this step:

- accept the production record field name already present in WASAPI responses
- if multiple plausible URL field names exist, normalize that in one helper
- skip records without a usable download URL and log that decision clearly

Do not over-generalize beyond what the current production records require.

---
## Orchestration Integration Requirement

Extend the current sequential flow in `lib/orchestration.py` so that after discovery and planned-path computation it can:

1. inspect discovered records for usable filenames and source URLs
2. pair those records with planned local WARC destinations
3. call the downloader helper
4. log success/failure counts clearly

Do this without turning `main.py` into a logic-heavy script.

If necessary, keep orchestration limited to a small, direct call path rather than introducing a broader job abstraction yet.

---
## Test Requirements

Add focused `unittest` coverage.

### Minimum tests to include

- **Partial-path construction**
  - destination `file.warc.gz` produces `file.warc.gz.partial`

- **Download happy path**
  - streamed bytes are written to a partial file
  - the final file exists after atomic rename
  - no leftover partial file remains

- **Existing stale partial handling**
  - a pre-existing partial file does not break a fresh download attempt

- **HTTP failure behavior**
  - a failing HTTP response returns or raises a clear error
  - the final destination is not left in a misleading partial-success state

- **Orchestration consumption**
  - the sequential orchestration can invoke the downloader for usable discovered records
  - records missing a usable source URL are skipped cleanly

Keep tests local and mocked; do not add live network tests.

---
## Suggested Implementation Notes

- Keep download logic in `lib/`, not in `main.py`.
- Use `pathlib.Path` throughout.
- Make parent directories before writing.
- Prefer explicit chunked writes over reading the full response into memory.
- Match repository style from `AGENTS.md` and `ruff.toml`.
- Keep return values explicit enough that later steps can add manifest updates and fixity writing without redesigning the downloader.

---
## Success Criteria

- [ ] a production downloader module exists under `lib/`
- [ ] the downloader streams content with `httpx`
- [ ] downloads are written to `*.partial` first
- [ ] successful downloads are atomically renamed into place
- [ ] stale partial files do not break retries
- [ ] the sequential orchestration flow can invoke the downloader for usable records
- [ ] focused `unittest` coverage exists for happy-path, failure, and orchestration behavior

---
## Likely Follow-Up After This Step

After the downloader is implemented and integrated, the next step should likely be:

1. add SHA-256 calculation and sidecar writing
2. update local manifest entries for download success/failure
3. then decide whether spreadsheet updates or Trio worker structure should come next

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
- `lib/storage_layout.py` now maps discovered filenames to deterministic local destinations.
- The next missing production dependency is the actual download write path.

The immediate objective is to add the smallest correct downloader layer that plugs into the existing sequential orchestration flow and writes WARC files safely using `*.partial` plus atomic rename.

---
