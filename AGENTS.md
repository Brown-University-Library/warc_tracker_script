# AGENTS.md — Repository Agent Instructions (Source of Truth)

This file defines the canonical coding directives for this repository.

If other instruction files exist (Copilot, IDE rules, contributor docs) and conflict with this file, follow this file and treat the others as stale.


## Index

- [Project basics](#project-basics)
- [Project index](#project-index)
- [How to run code](#how-to-run-code)
- [Coding directives (Python)](#coding-directives-python)
- [Django architecture conventions](#django-architecture-conventions)
- [Front-end change guidance](#front-end-change-guidance)
- [Tests](#tests)
- [Change workflow expectations](#change-workflow-expectations)
- [If instructions are missing or ambiguous](#if-instructions-are-missing-or-ambiguous)


## Project basics

- Primary language: Python
- Target runtime: Python 3.12 -- unless a `pyproject.toml` specifies a different version
- Dependency / execution tool: `uv`
- Project-root is the directory containing this file (and `.git/`, and `.gitignore`).


## Project index

- `main.py` is the production entry point. It loads `.env`, requires `LOG_PATH`, configures logging, reads `GSHEET_SPREADSHEET_ID`, Archive-It credentials, `WARC_STORAGE_ROOT`, and `ARCHIVEIT_WASAPI_BASE_URL`, then runs the sequential collection orchestration.
- `lib/orchestration.py` is the main workflow coordinator. It handles startup spreadsheet coordination, `DEV_COLLECTIONS` filtering, discovery mode selection, spreadsheet status transitions, download planning, manifest reconciliation, download/fixity execution, final reporting, and failure reporting. Its final on-disk collection totals currently scan `collections/<collection_id>/<seed_id>/<year>/<month>/*.warc.gz`.
- `lib/collection_sheet.py` owns Google Sheets access and worksheet contracts: service-account credentials, the `At Collection Level` worksheet, header alias matching, active collection parsing, required reporting-column validation, and batched status/summary writes.
- `lib/wasapi_discovery.py` owns Archive-It WASAPI enumeration: UTC datetime parsing/formatting, overlap-window checkpoint boundaries, paginated fetches, record extraction, next-page detection, max `store-time` checkpointing, and partial discovery errors.
- `lib/storage_layout.py` maps WARC filenames to local storage paths. It extracts seed id plus year/month from WARC filenames and plans `collections/<collection_id>/<seed_id>/<year>/<month>/...` with matching fixity files stored next to the WARC. It currently expects the normal Archive-It long timestamp pattern (`-YYYYMMDDHHMMSS...-`) for year/month extraction; simple uploaded/external names such as `SEED4660252-20260529.warc` need explicit parser and test updates before they will map correctly.
- `lib/local_state.py` owns per-collection `state.json`: default state, load/normalize validation, atomic saves, and durable file-manifest updates for planned, downloaded, failed, and fixity states.
- `lib/downloader.py` streams one URL to disk with `*.partial` files and atomic replacement, returning a `DownloadResult` instead of raising for normal download failures.
- `lib/fixity.py` computes SHA-256, validates existing sidecars, and writes `.sha256` and `.json` fixity files atomically.
- `validate_spreadsheet_connection.py` is a standalone development CLI for checking whether a configured or supplied spreadsheet can be opened, parsed, and edited before running the production backup workflow.
- `cron_scripts/check_for_unknown_seeds.py` is a cron-oriented development/operations script that scans storage for `*.warc.gz` files under `UNKNOWN_SEED` folders and sends an email alert to recipients configured in dotenv. If plain `.warc` downloads are supported later, update this scanner, orchestration totals, and tests together.
- `tmp_inspect_collection_wasapi.py` is an investigative CLI for capturing raw WASAPI metadata pages and derived summaries for one collection; it does not download WARC files.
- `other/gsheet_screenshots.py` is a standalone Playwright/uv script for recurring Google Sheet screenshots.
- `run_tests.py` is the unittest runner; use `uv run ./run_tests.py` for all tests or pass dotted unittest targets for focused runs.
- `tests/` mirrors the core modules, with the broadest behavioral coverage in `tests/test_orchestration.py`.
- `README.md` explains the operational model: active collections come from the sheet, local storage is the source of truth, first runs do full backfill, later runs use a 30-day `store-time` overlap, and spreadsheet writes are coarse reporting checkpoints.


## How to run code

- Assume user is in the project-root directory.
- Do not use `python` to run scripts.
- Run a script via: `uv run ./path_to_script.py --help`
- Run tests via:
    - `uv run ./run_tests.py`
        - Note that `run_tests.py` has usage instructions about how to run more granular tests.
- Run django management scripts via: `uv run ./manage.py THE-COMMAND`


## Coding directives (Python)

### Type hints and imports

- Use Python 3.12 type hints everywhere (functions and important variables). (Unless a `pyproject.toml` specifies a different version.)
- Prefer builtin generics (e.g., `list[str]`, `dict[str, int]`) over `typing.List` / `typing.Dict`.
- Prefer PEP 604 unions (e.g., `str | None`) over `Optional[str]`.
- Avoid `typing` and `annotations` imports unless strictly necessary.

### Script structure

- Structure runnable modules as:
  - `def main() -> None: ...`
  - `if __name__ == '__main__': main()`
- Keep `main()` simple: parse args / orchestrate calls only.
- Put real logic into top-level helper functions and modules (no nested function definitions).
- Rarely use more than three levels of hierarchy: main() can call helper_A() which can call helper(B) which can, if necessary, can call helper(C) -- but that's it.

### Functions and control flow

- Prefer single-return functions (use local variables and a final return).
- Do not define functions inside other functions.
- Favor clarity and explicitness over cleverness.

### HTTP and networking

- Use `httpx` for all HTTP calls.
- Do not introduce alternate HTTP libraries (e.g., `requests`, `aiohttp`) unless the repository already depends on them and there is a documented reason.

### Docstrings

- Use triple-quoted docstrings.
- Write docstrings in present tense, with triple-quotes on their own lines.
  - Good: 
    ```
    """
    Parses ...
    """
    ```
  - Avoid: `"""Parse ..."""`
- The last line of non-test function-docstrings should be: `Called by: the_caller_function()` (or, if in another class/module, `Called by: module.Class.the_caller_function()`)
- Start test-function docstring-text with "Checks..."
- For header-comments, in functions, start the comment with two hashes (e.g., `## does this`).

### Additonal coding directives

- inspect the `/ruff.toml` for additional coding directives, such as `max-line-length` and `quote-style`.


## Django architecture conventions

### View-layer responsibilities

- `project/app/views.py` should contain **only** view functions that directly handle URL endpoints.
- Every view function in `project/app/views.py` should correspond to an entry in `project/config/urls.py`.
- Views should act as **manager/orchestrator** functions:
  - Parse request input (query params, POST body, files)
  - Perform minimal validation and shaping of inputs
  - Delegate substantive work to modules under `project/app/lib/`
  - Convert returned results into the appropriate `HttpResponse` (HTML, JSON, redirects)

### Business logic placement

- Put domain logic, integrations, and reusable operations in `project/app/lib/` (not in `views.py`).
- If multiple endpoints share logic, move that shared logic into `project/app/lib/` and keep each view thin.
- Prefer pure, testable functions in `project/app/lib/` that accept plain Python values (not Django request objects)
  unless passing the request is necessary for a narrow, well-justified reason.

### Imports and dependencies

- `views.py` should primarily import:
  - Django primitives (`HttpRequest`, `HttpResponse`, `render`, `redirect`, etc.)
  - The minimal set of functions/classes from `project/app/lib/` needed for each endpoint
- Avoid creating a secondary abstraction layer inside `views.py` (no view-helper utilities); place helpers in `project/app/lib/`.


## Front-end change guidance

- When front-end changes are required, use JavaScript only where it is truly required.
- Prefer updates in CSS, Python code, or Django template code when those can satisfy the behavior or presentation need.


## Tests

- Use the standard library `unittest` framework (not pytest) for non-Django projects.
- Use Django's test framework for Django projects.
- New behavior should usually come with a focused test covering:
  - the happy path
  - at least one failure / edge case


## Change workflow expectations

When implementing a change (especially from an issue/task):

1. Read relevant surrounding code and match existing conventions.
2. Make the smallest correct change that satisfies the request.
3. Update tests and run: `uv run ./run_tests.py`
4. If you cannot run tests in your environment, still write/adjust tests and state what you would run.


## If instructions are missing or ambiguous

- Do not ask questions unless absolutely necessary to proceed.
- Make reasonable assumptions, state them explicitly, then implement.
- If blocked, provide:
  - what you tried
  - what you found in the repo
  - a concrete next step (command, file to edit, or minimal decision needed)

---
