# Next Single Step: Temporary Single-Collection WASAPI Metadata Capture Script

## Context for Future Agents

**Code-directives**: review `warc_tracker_script/AGENTS.md` before editing code.

**Master plan reference**: `warc_tracker_script/PLAN__simplified_warc_backup_script_v05.md`

**Current implementation status**:

- Sheet ingestion is already implemented in `warc_tracker_script/lib/collection_sheet.py`.
- The manager/orchestrator is currently minimal in `warc_tracker_script/main.py`.
- The simplified v05 plan currently assumes a per-collection local storage layout of:
  - `collections/{collection_id}/warcs/{filename}`
  - `collections/{collection_id}/fixity/{filename}.sha256`
  - `collections/{collection_id}/fixity/{filename}.json`
  - `collections/{collection_id}/state.json`
- That storage assumption has not yet been validated against real Archive-It / Internet Archive metadata patterns.

**Important current code facts**:

- The project uses Python `3.12` per `pyproject.toml`.
- Use `httpx` for HTTP work.
- Tests should use `unittest`, not `pytest`.
- `ruff.toml` uses single quotes and a max line length of `125`.

---
## Goal of This Step

Create a **temporary investigative script plan** for a script that:

- accepts a single Archive-It `collection_id`
- performs one or more Archive-It / Internet Archive WASAPI lookups
- downloads the JSON metadata needed for later manual inspection
- writes that metadata to a caller-provided target directory
- does **not** download WARC payload files
- does **not** make the final storage-layout decision

The purpose of the future script is to gather enough real metadata to answer this question:

- should the simplified backup plan keep a flat per-collection filename layout, or
- should it introduce an identifier-derived subdirectory or pairtree-like naming convention?

---
## Why This Is the Right Next Step

1. **It de-risks the storage-layout decision early**
   - The simplified plan currently assumes that saving files as `warcs/{filename}` is sufficient.
   - That assumption may be correct, but it should be checked against real metadata before path-building and state logic are implemented around it.

2. **It keeps the investigation narrow**
   - This step is not an OCFL implementation step.
   - This step is only about collecting real metadata for inspection.

3. **It may prevent unnecessary complexity**
   - If real metadata shows that filenames are already unique and path-safe enough, then the simplified plan can stay simple with more confidence.
   - If real metadata shows collisions, awkward identifiers, or grouping needs, that can be addressed before the downloader is built.

4. **It avoids baking in stale assumptions**
   - The prior next-step plan targeted local state management first.
   - This temporary investigative step is now more valuable because the storage naming decision affects local path design, manifest keys, and fixity sidecar placement.

---
## Scope Boundaries for This Step

### In scope

- Plan a temporary standalone script.
- Limit the script to a **single collection id** per invocation.
- Fetch and persist JSON metadata only.
- Define the target directory structure for captured metadata.
- Define what metadata should be preserved so it can be inspected later without repeating network calls.
- Define a small amount of summary output that helps confirm what was captured.

### Out of scope

- No WARC downloads.
- No spreadsheet reads.
- No spreadsheet writes.
- No local state / checkpoint implementation for the main backup workflow.
- No Trio concurrency.
- No OCFL implementation.
- No automatic determination of the final naming convention.
- No broad refactor of `main.py`.

---
## Core Question the Future Script Must Help Answer

The future script should collect enough metadata to support inspection of the following:

- Are WARC filenames unique within a collection?
- Do records expose a stable identifier that is more suitable than filename for local path construction?
- Are there multiple metadata records that would map to the same local filename?
- Are filenames path-safe as-is, or do they contain problematic characters or lengths?
- Is there evidence that files naturally group under an Internet Archive identifier that would justify a subdirectory layer?
- Is there any practical reason to consider pairtree-like path derivation, or would that be needless complexity for MVP?

The future script should not answer these questions automatically, but it should capture the data necessary for a human to answer them.

---
## Recommended Script Shape

Create a temporary script such as:

- `warc_tracker_script/tmp_inspect_collection_wasapi.py`

This future script should be treated as:

- investigative
- standalone
- safe to discard later once the storage convention is decided

Recommendation:

- keep the script independent from the production backup flow
- keep it out of `main.py`
- put any reusable HTTP or parsing helpers in `lib/` only if that happens naturally and stays small

---
## Expected CLI Behavior

The future script should accept at least:

- `--collection-id` or positional `collection_id`
- `--output-dir` for the destination directory

Optional but useful flags:

- `--max-pages` to limit collection paging during exploration
- `--log-level`
- `--overwrite` or `--resume` behavior, if needed

Recommendation:

- fail clearly if required arguments are missing
- create the output directory if it does not exist
- refuse to overwrite existing files unless explicitly allowed, or use predictable file names that can be safely replaced

---
## Metadata to Capture

The future script should save enough raw metadata to support both detailed inspection and later reproducibility.

### Minimum required captures

For a given collection, preserve:

1. **Collection request metadata**
   - the collection id used
   - request timestamps
   - request URLs actually called
   - any paging parameters used

2. **Raw WASAPI response pages**
   - save each JSON page as returned
   - preserve page ordering
   - do not reduce these to only a handpicked subset of fields

3. **A lightweight manifest / index file**
   - list the saved JSON files
   - record page count
   - record total item count if determinable
   - record any request failures or truncation decisions

4. **A derived summary file**
   - include a human-readable high-level summary of key metadata traits
   - for example: distinct filenames, duplicate filenames, observed identifiers, suspicious path characters, long filenames

### Nice-to-have captures

If the API responses expose them, preserve fields relevant to later path analysis such as:

- filename
- original filename if distinct
- item identifier
- crawl identifier
- store-time
- file size
- download URL
- collection identifier repeated inside records
- any parent/child or grouping fields

The raw response pages are the most important artifact. The summary is secondary.

---
## Output Layout Recommendation

Use a directory layout that makes manual inspection straightforward.

```text
{output_dir}/
  collection_{collection_id}/
    request_manifest.json
    pages/
      page_0001.json
      page_0002.json
      ...
    derived_summary.json
    derived_summary.md
```

Notes:

- Keep the raw pages separate from derived summary artifacts.
- Use stable, zero-padded page numbering.
- Preserve enough request context in `request_manifest.json` so the capture can be understood later.
- The output layout for this temporary script does not need to match the final production backup layout.

---
## HTTP / API Behavior Requirements

The future script should:

- use `httpx`
- authenticate using environment variables already intended for Archive-It access
- follow WASAPI paging until all pages are retrieved, unless a deliberate exploration limit such as `--max-pages` is used
- log each request clearly enough that failures can be understood
- fail clearly on authentication problems or malformed responses

Recommendation:

- keep retry behavior minimal and practical
- preserve partial results if some pages were fetched before failure
- record failures in the manifest rather than silently discarding them

---
## Data Preservation Requirements

The future script should optimize for later inspection.

1. **Prefer raw preservation over aggressive transformation**
   - Save raw response JSON pages first.
   - Derived summaries should never be the only artifact.

2. **Make outputs inspectable without rerunning the script**
   - A later session should be able to review the saved directory and answer naming-structure questions without hitting the network again.

3. **Record enough provenance**
   - Include timestamps, called URLs, and collection id in saved metadata.

4. **Do not over-normalize identifiers**
   - If a field appears in raw JSON, preserve it as-is.
   - Normalization can happen later in analysis code if needed.

---
## Recommended Derived Analysis to Include

The future script should optionally compute a small derived summary to accelerate human review.

Recommended summary sections:

- total records observed
- total pages saved
- count of records with filenames
- count of distinct filenames
- list or sample of duplicate filenames
- count of records with identifier-like fields
- distinct identifier field names observed
- examples of filename/path anomalies
- top-level note on whether a flat filename layout appears obviously safe, obviously unsafe, or still unclear

Important:

- the summary should be descriptive, not prescriptive
- it should not claim to make the final storage-design decision

---
## Suggested Implementation Structure

For the future implementation, a reasonable structure would be:

- temporary script module for CLI and orchestration
- small helper functions for:
  - building request URLs or params
  - fetching paginated JSON
  - saving raw pages
  - generating the request manifest
  - generating a derived summary

Possible helper names:

```python

def fetch_collection_wasapi_pages(...) -> list[dict[str, object]]:
    ...


def save_raw_wasapi_pages(...) -> list[Path]:
    ...


def build_capture_manifest(...) -> dict[str, object]:
    ...


def build_metadata_summary(...) -> dict[str, object]:
    ...
```

These names are illustrative only. Keep the implementation small and direct.

---
## Test Expectations

Because this is a temporary investigative script, keep testing proportionate.

### In scope for tests

- pure helper functions that summarize metadata
- path-building helpers for the capture directory
- manifest-generation helpers

### Out of scope for heavy testing

- full live-network integration tests
- large mocking harnesses unless they stay very small

If tests are written, use `unittest`.

---
## Success Criteria

- [ ] the new next-step plan targets a temporary metadata-capture script rather than local-state management
- [ ] the planned script is limited to a single `collection_id` per run
- [ ] the planned script is clearly described as metadata-only and non-production
- [ ] the plan requires saving raw paginated JSON responses for later inspection
- [ ] the plan defines an inspectable output directory structure
- [ ] the plan keeps the final naming-convention decision explicitly deferred

---
## Likely Follow-Up After This Step

After the future script is implemented and run against a handful of real collections:

1. inspect the saved metadata
2. decide whether the simplified plan should keep:
   - flat `warcs/{filename}` storage, or
   - a shallow identifier-derived subdirectory, or
   - a pairtree-like naming convention
3. update `PLAN__simplified_warc_backup_script_v05.md` if needed
4. write the next implementation plan for the actual production step after that decision is made

---
## Handoff Notes for the Next Agent / New Session

If you are picking this up in a new session, start by re-reading:

- `warc_tracker_script/AGENTS.md`
- `warc_tracker_script/PLAN__simplified_warc_backup_script_v05.md`
- `warc_tracker_script/PLAN__next_single_step.md`
- optionally `warc_tracker_script/OLD_PLAN__next_single_step.md` for the deferred local-state plan

Quick mental model of the codebase right now:

- `main.py` is still intentionally small.
- `lib/collection_sheet.py` is the main completed library module so far.
- The immediate question is not downloader implementation; it is whether real metadata supports the current simplified storage naming assumption.

The next implementation should preserve these architectural directions:

- keep production logic simple
- keep temporary investigation code separate from production orchestration
- preserve raw metadata for later review
- avoid prematurely adopting OCFL-style complexity unless real data shows a clear need
