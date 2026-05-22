# Plan: seed-based storage layout and updated spreadsheet fields

## Context

This plan is for `warc_tracker_script`, a Python 3.12 project run with `uv`.

Primary project files to review before implementation:

- `AGENTS.md` for coding directives.
- `README.md` for project purpose and operator workflow.
- `main.py` for CLI/environment setup.
- `lib/orchestration.py` for WASAPI discovery, download planning, run coordination, and final reporting.
- `lib/storage_layout.py` for WARC/fixity path construction and on-disk summary scans.
- `lib/collection_sheet.py` for Google Sheets parsing, validation, and status/summary writes.
- `validate_spreadsheet_connection.py` for development-time spreadsheet validation.
- `tests/` for the expected unit-test style.

Project conventions that matter for this work:

- Run scripts from the project directory with `uv run ./script_name.py`; `.env` is loaded from there.
- Use `uv run ./run_tests.py` for tests.
- The spreadsheet id can come from `GSHEET_SPREADSHEET_ID`.
- Archive-It WASAPI credentials are available from dotenv when commands are run from the project directory.
- Local WARC storage root comes from `WARC_STORAGE_ROOT`.
- Keep code changes focused, use top-level helper functions rather than nested functions, and prefer clear dataclasses for structured state.

Client/request context:

- The client asked for WARC files to be saved by seed id:
  `collections/<collection_id>/<seed_id>/<year>/<month>/<filename>`.
- The client copy spreadsheet has revised collection-level reporting columns.
- Some old spreadsheet columns are struck through and should not be updated.
- The plan assumes current development data can be deleted manually; no old-layout migration is needed.
- Seed folders should use the self-describing form `SEED2761639`.
- WARC files without a parseable seed id should go under `UNKNOWN_SEED`.
- Add a cron-oriented checker for `UNKNOWN_SEED` files and email named recipients from dotenv.

## Context reviewed

- Reviewed `AGENTS.md` and followed the project directives: Python 3.12 style, `uv` execution, `unittest`, no nested functions, single-return preference, and keeping production logic in focused helpers/modules.
- Reviewed `README.md`: this script backs up Archive-It WARC files for active spreadsheet collections, treats local storage as source of truth, uses WASAPI `store-time` checkpointing, and writes coarse collection-level status back to Google Sheets.
- Ran `uv run ./validate_spreadsheet_connection.py` against the environment spreadsheet. The connection succeeded, but the sheet failed the current column contract because the reporting column labels changed.
- Inspected the target Google Sheet metadata and formatting for `At Collection Level`, including struck-through cells.
- Sampled live WASAPI metadata for collection `11926`. The records include fields such as `collection`, `crawl`, `filename`, `locations`, `size`, and `store-time`. The sampled records do not include a dedicated seed field, but the WARC filename embeds seed ids such as `SEED2761639`.

## Spreadsheet findings

The current `At Collection Level` sheet uses row 3 as the effective header row. Important active columns:

- `B` `Collection ID`
- `C` `Repository`
- `D` `Collection URL`
- `E` `Collection name`
- `H` `Seed Count`
- `L` `Active/Inactive`
- `M` `Notes`
- `N` `status-last-fetch`
- `O` `status-last-fetch-file-count`
- `P` `last-download-timestamp`
- `Q` `total-col-WARC-count`
- `R` `total-downloaded-collection-size`
- `S` `server-file-path-collectionLevel`

Columns that appear intentionally superseded:

- `F` `Total Size` is struck through and row 1 says it is not needed because column `R` replaces it.
- `G` `File Count ?` is struck through and row 1 says it is not needed because column `Q` replaces it.
- `I` `Server File path- collection level` is struck through and row 1 says it is not needed because column `S` replaces it.
- `J` `Last WASAPI fetch` is struck through and row 1 says it is not needed because column `P` replaces it.

The current code still expects old/internal reporting aliases:

- `processing_status_main`
- `processing_status_detail`
- `summary_status_last_wasapi_check`
- `summary_status_downloaded_warcs_count`
- `summary_status_downloaded_warcs_size`
- `summary_status_server_path`

Those must be remapped to the new labels before the production script can validate or update the client copy.

## New processing-update fields

Use these canonical internal fields and sheet aliases going forward:

| Canonical field | Sheet label | Existing rough equivalent | Meaning |
| --- | --- | --- | --- |
| `status_last_fetch` | `status-last-fetch` | `processing_status_main` | Coarse collection status for the latest run/fetch. Reuse existing status values unless stakeholders want wording changes. |
| `status_last_fetch_file_count` | `status-last-fetch-file-count` | part of `processing_status_detail` | Numeric count of WARC files discovered by WASAPI during the latest fetch/run. |
| `last_download_timestamp` | `last-download-timestamp` | `summary_status_last_wasapi_check` | Timestamp when the script finished its latest processing/reporting pass for that collection. |
| `total_col_warc_count` | `total-col-WARC-count` | `summary_status_downloaded_warcs_count` | Cumulative on-disk WARC count for the collection. |
| `total_downloaded_collection_size` | `total-downloaded-collection-size` | `summary_status_downloaded_warcs_size` | Cumulative on-disk WARC size for the collection, formatted as GB/TB. |
| `server_file_path_collection_level` | `server-file-path-collectionLevel` | `summary_status_server_path` | Local collection root path. |
| `seed_count` | `Seed Count` | new | Observed WARC seed count: distinct `SEED...` identifiers observed in WASAPI WARC filenames and/or local state. |

Status values can initially remain:

- `discovery-in-progress`
- `download-planning-complete`
- `downloading-in-progress`
- `no-new-files-to-download`
- `downloaded-without-errors`
- `completed-with-some-file-failures`
- `discovery-failed`
- `spreadsheet-update-failed`

Recommended adjustment: because `status-last-fetch-file-count` appears to want a number, stop writing free-text detail into that column. Keep free-text detail in logs and `state.json`; only write a numeric value to the sheet.

## Seed-based download structure

Requested WARC path shape:

```text
collections/<collection_id>/<seed_id>/<year>/<month>/<filename>
```

Example:

```text
collections/11926/SEED2761639/2026/05/ARCHIVEIT-11926-WEEKLY-JOB2703309-0-SEED2761639-20260519225714856-00000-wcrsf28b.warc.gz
```

Implementation plan:

1. Add seed parsing to `lib/storage_layout.py`.
   - Add a regex such as `(?:^|-)SEED(?P<seed_digits>[0-9]+)(?:-|$)`.
   - Return a normalized seed folder value, preferably `SEED<digits>`.
   - Preserve existing timestamp parsing.

2. Extend `PlannedCollectionPaths`.
   - Add `seed_id: str`.
   - Update path builders to include `seed_id`.
   - Update tests in `tests/test_storage_layout.py`.

3. Store fixity files next to the WARC files.
   - Use this path shape:
     `collections/<collection_id>/<seed_id>/<year>/<month>/<filename>.sha256`
   - This keeps each seed/year/month folder self-contained and matches the requested operator-facing structure.

4. Update download planning.
   - `build_planned_download_paths()` and `build_planned_downloads()` should pass the parsed `seed_id` from the filename into storage planning.
   - Records without parseable seed ids should be placed under `UNKNOWN_SEED` and counted/reported as warnings, so backup work does not silently skip files.
   - Add `cron_scripts/check_for_unknown_seeds.py` to periodically scan for files under any `UNKNOWN_SEED` folder and send an email notification if any are found.
   - Use `UNKNOWN_SEED_ALERT_RECIPIENTS` as the dotenv variable for notification recipients.
   - Treat `UNKNOWN_SEED_ALERT_RECIPIENTS` as JSON containing a list of two-item tuples/lists: `(name, email_address)`.
   - Example dotenv value:
     `UNKNOWN_SEED_ALERT_RECIPIENTS='[["Birkin", "birkin@example.edu"], ["Archive Team", "archive-team@example.edu"]]'`

5. Update manifest/state handling.
   - Keep manifest keys by filename for now to preserve dedupe behavior.
   - Add `seed_id` to each file entry.
   - Store the new `warc_path`, `sha256_path`, and `json_path`.
   - Preserve existing retry and reconciliation logic.

6. Do not implement old-layout migration.
   - This is still development data.
   - Existing downloaded data will be deleted manually and rebuilt from a clean run.
   - Keep implementation focused on the new layout only.

7. Update on-disk summary totals.
   - `iter_collection_warc_paths()` currently scans `collections/<id>/warcs/**/*.warc.gz`.
   - Change it to scan the new seed tree.
   - Do not scan the old `warcs/` layout.

## Seed count in column H

There are two possible meanings for `Seed Count`:

1. **Configured Archive-It seed count:** total number of seeds in the collection, including seeds that may have no WARC files in the current WASAPI result set.
2. **Observed WARC seed count:** number of distinct `SEED...` identifiers observed in WASAPI WARC filenames and/or local state.

The implementation difficulty is different:

- Observed WARC seed count is easy to compute while processing WASAPI records and local state.
- Configured Archive-It seed count may require another Archive-It endpoint/API or a separate seed-level sheet because WASAPI `webdata` records only showed seed ids embedded in filenames, not a separate complete seed inventory.

Important observation:

- The spreadsheet sample shows collection `11926` with `Seed Count = 83`.
- Older captured WASAPI metadata for collection `11926` has fewer distinct `SEED...` values when parsed from WARC filenames, so column H may be intended as configured seed count rather than observed downloaded-WARC seed count.

Decision for now:

- Treat `Seed Count` as observed WARC seed count.
- Compute it as the number of distinct `SEED...` identifiers observed in WASAPI WARC filenames and/or local state.
- Write this observed count to column H.
- If the client later clarifies that column H means configured Archive-It seed total, change the implementation to use the correct Archive-It source or another confirmed source.

## Spreadsheet implementation plan

1. Update `HEADER_ALIASES` in `lib/collection_sheet.py`.
   - Map existing canonical fields to new labels where the meaning is still equivalent.
   - Add new canonical names where semantics changed.
   - Keep old labels as aliases during transition so the script works against both the copy and original sheet.

2. Split reporting dataclasses if needed.
   - Current `CollectionProcessingStatusUpdate` assumes two text status fields.
   - New column `status-last-fetch-file-count` appears numeric.
   - Prefer a new dataclass with explicit fields:
     - `status_last_fetch: str`
     - `status_last_fetch_file_count: str`
     - `last_download_timestamp: str`
     - `total_col_warc_count: str`
     - `total_downloaded_collection_size: str`
     - `server_file_path_collection_level: str`
     - `seed_count: str`

3. Update write helpers.
   - `build_collection_status_cell_updates()`
   - `build_collection_summary_cell_updates()`
   - `update_collection_processing_status()`
   - `update_collection_final_reporting()`

4. Update validation script.
   - Keep `validate_spreadsheet_connection.py` useful for development by reporting which expected fields were found/missing.
   - Consider adding a `--show-column-map` option later, but this is not necessary for the first implementation.

5. Update tests.
   - Header parsing with new labels and old labels.
   - Missing required new columns.
   - Status/summary write ranges for row 3 labels.
   - Struck-through/duplicate old columns should not be used when active replacement columns exist.

## Suggested implementation slices

1. **Spreadsheet compatibility slice**
   - Update header aliases and reporting fields.
   - Keep storage layout unchanged.
   - Verify validation script passes against the copy spreadsheet.
   - Tests: collection sheet parsing/writes.

2. **Seed parsing/storage layout slice**
   - Add seed-id extraction and seed-based paths.
   - Update path planning and tests.
   - Store fixity files next to WARC files.
   - Add `UNKNOWN_SEED` handling.
   - Tests: storage layout, planned downloads, unknown seed handling.

3. **State and unknown-seed monitoring slice**
   - Update state paths for the new layout.
   - Do not implement old-layout migration.
   - Add `cron_scripts/check_for_unknown_seeds.py`.
   - Add `UNKNOWN_SEED_ALERT_RECIPIENTS` dotenv support for JSON recipient pairs.
   - Tests: new state paths, unknown seed scan, recipient parsing.

4. **Seed count slice**
   - Implement `observed_seed_count`.
   - Write observed WARC seed count to column H.
   - Document that this may change later if the client wants configured Archive-It seed total instead.

5. **End-to-end reporting slice**
   - Update final reporting to the new field set.
   - Run against a small active test row in the copy spreadsheet.
   - Confirm sheet values and on-disk layout with the client before merging changes back to the original spreadsheet.

## Decisions and remaining questions

1. Seed folders should be named `SEED2761639`, not just `2761639`.
   - This is self-describing and matches filenames/schema.

2. Fixity files should live next to the WARC files.
   - Do not use a separate parallel `fixity/` tree for this change.

3. WARC files without a parseable `SEED...` in the filename should be stored under `UNKNOWN_SEED`.
   - Add logging/reporting for the count of files stored there.
   - Add `cron_scripts/check_for_unknown_seeds.py` to scan for `UNKNOWN_SEED` files periodically and email `UNKNOWN_SEED_ALERT_RECIPIENTS`.

4. Existing downloaded files should not be migrated.
   - Existing development data will be deleted manually and rebuilt from a clean run.

5. Column H `Seed Count` should mean observed WARC seed count for now.
   - The other possible meanings are configured Archive-It seed total or distinct seed ids currently represented on disk.
   - Chosen meaning: distinct `SEED...` identifiers observed in WASAPI WARC filenames and/or local state.
   - This can be changed later if the client clarifies a different meaning.

6. `status-last-fetch-file-count` should count files discovered by WASAPI in the latest fetch.
   - Other possibilities considered: files planned for download, or files successfully downloaded in this run.
   - Chosen meaning: latest-run discovered WARC count, because the label says `last-fetch-file-count`.

7. Status values should remain machine-oriented slugs.
   - Keep values such as `downloaded-without-errors` unless the client specifically requests display wording changes.

8. The script should not update struck-through columns.
   - Treat them as deprecated duplicates.
   - They will be removed from the spreadsheet.

9. The seed-level worksheet is not part of this change.
   - The current scope is collection-level seed count and seed-based storage folders.

## Deferred questions

1. What is the exact email delivery mechanism for `cron_scripts/check_for_unknown_seeds.py`?
   - Options include a local `sendmail` command, SMTP environment variables, or an existing institutional mail relay.
   - The recipient list variable should be `UNKNOWN_SEED_ALERT_RECIPIENTS`.
   - `UNKNOWN_SEED_ALERT_RECIPIENTS` should parse to a list of `(name, email_address)` pairs.

2. Will the client later want `Seed Count` to mean configured Archive-It seed total instead of observed WARC seed count?
   - For now, the implementation will use observed WARC seed count.

## Acceptance criteria

- `uv run ./validate_spreadsheet_connection.py` succeeds against the updated copy spreadsheet after alias/reporting changes.
- Active rows are parsed from the new row-3 headers.
- Downloaded WARC files are stored under `collections/<collection_id>/<seed_id>/<year>/<month>/`.
- Fixity files are stored next to the WARC files.
- WARC files without parseable seed ids are stored under `UNKNOWN_SEED`.
- `cron_scripts/check_for_unknown_seeds.py` scans for `UNKNOWN_SEED` files and emails `UNKNOWN_SEED_ALERT_RECIPIENTS`.
- Final collection-level reporting writes only active new columns, not struck-through duplicates.
- The new final report includes:
  - `status-last-fetch`
  - `status-last-fetch-file-count`
  - `last-download-timestamp`
  - `total-col-WARC-count`
  - `total-downloaded-collection-size`
  - `server-file-path-collectionLevel`
  - `Seed Count` as observed WARC seed count.
- Existing tests are updated and pass with `uv run ./run_tests.py`.
