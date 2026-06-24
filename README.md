# warc-tracker-script

on this page...
- [Overview](#overview)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [What the script does](#what-the-script-does)
- [How it works in practice](#how-it-works-in-practice)
- [Current state of the project](#current-state-of-the-project)
- [FAQs](#faqs)
  - [store-time and lookback](#store-time-and-lookback)
  - [why is the local filesystem the source of truth?](#why-is-the-local-filesystem-the-source-of-truth)
  - [what gets stored for each collection?](#what-gets-stored-for-each-collection)
  - [spreadsheet updates](#spreadsheet-updates)


## Overview

This script backs up Archive-It WARC files for collections listed as active in a Google Sheets tracking spreadsheet.

At a high level, it checks which collections are active, asks WASAPI (Archive-It's Web Archiving Systems API) what WARC files are available, downloads anything missing, writes local fixity information, and updates the spreadsheet with collection-level progress.

The local filesystem is treated as the source of truth. The spreadsheet is mainly there to help monitor activity and control which collections are in scope.


## Requirements

- [uv](https://docs.astral.sh/uv/#installation)
- Google Cloud service-account credentials; the spreadsheet must be shared with the service-account's `client_email` as Editor so the script can write updates.


## Installation

Clone the repository:

```shell
cd /path/to/warc_tracker_script_stuff/
git clone git@github.com:Brown-University-Library/warc_tracker_script.git
cd warc_tracker_script
```

Run commands from the project root with `uv`.

Install/sync dependencies:

```shell
uv sync
```

Create a `.env` file. Required values for the production script are:

```shell
GSHEET_CREDENTIALS_JSON='{"type":"service_account", "...":"..."}'
GSHEET_SPREADSHEET_ID="the-google-sheet-id"
LOG_PATH="./logs/warc_tracker_script.log"
ARCHIVEIT_WASAPI_USERNAME="archive-it-username"
ARCHIVEIT_WASAPI_PASSWORD="archive-it-password"
```

Optional values:

```shell
LOG_LEVEL="INFO"
WARC_STORAGE_ROOT="/path/to/storage"
ARCHIVEIT_WASAPI_BASE_URL="https://warcs.archive-it.org/wasapi/v1/webdata"
RUN_COORDINATION_MODE="skip_spreadsheet_coordination_check"
DEV_COLLECTIONS="22900,15887"
UNKNOWN_SEED_ALERT_RECIPIENTS='[["Name One", "name.one@example.edu"], ["Name Two", "name.two@example.edu"]]'
UNKNOWN_SEED_ALERT_FROM_EMAIL="warc-tracker@example.edu"
UNKNOWN_SEED_ALERT_SMTP_HOST="localhost"
UNKNOWN_SEED_ALERT_SMTP_PORT="25"
```

`RUN_COORDINATION_MODE` is normally unset. When it is unset, startup checks active spreadsheet rows and refuses to start if any row already has a blocking in-progress status such as `discovery-in-progress` or `downloading-in-progress`. Set `RUN_COORDINATION_MODE="skip_spreadsheet_coordination_check"` only when an external cron or scheduler lock already guarantees that two copies of the script cannot run at the same time; that setting skips the spreadsheet coordination preflight.

`DEV_COLLECTIONS` is optional and intended for local development or dev-server testing. When set, it limits processing to the listed active spreadsheet collection rows while still validating the spreadsheet contract. Values may be comma- or whitespace-separated collection IDs. Requested IDs must already exist as active collection rows so status updates can target the correct spreadsheet rows.

`UNKNOWN_SEED_ALERT_RECIPIENTS` is used by `cron_scripts/check_for_unknown_seeds.py`. It must be JSON that parses to a list of `(name, email_address)` pairs.


## Usage

Run the backup workflow:

```shell
uv run ./main.py
```

Validate that a spreadsheet can be opened, parsed, and edited before running the backup workflow:

```shell
uv run ./validate_spreadsheet_connection.py --spreadsheet-id the-google-sheet-id
```

Run tests:

```shell
uv run ./run_tests.py
uv run ./run_tests.py -v tests.test_orchestration
```

Capture WASAPI metadata for one collection without downloading WARC files:

```shell
uv run ./tmp_inspect_collection_wasapi.py --collection-id 12345 --output-dir ./wasapi_inspection
```

Check for downloaded WARC files that could not be assigned to a seed folder:

```shell
uv run ./cron_scripts/check_for_unknown_seeds.py --dry-run
uv run ./cron_scripts/check_for_unknown_seeds.py
```


## What the script does

- Reads the tracking spreadsheet and selects active collections.
- Checks Archive-It WASAPI for WARC files associated with those collections.
- Downloads WARC files that are not yet backed up locally.
- Writes SHA-256 fixity-checksum files for downloaded WARCs
- Records per-collection state on disk so later runs can continue safely.
- Updates the spreadsheet with simple collection-level progress and summary information.


## How it works in practice

- The script will be run via a cron-job, but can also be run manually.
- On a collection's first successful run, the script aims to do a full historical backfill.
- On later runs, it re-checks a recent overlap window so that interrupted or partial runs are less likely to miss files.
- Files are downloaded into a predictable collection/seed/year/month folder structure.
- Each collection keeps a local `state.json` file so the script can remember what it has already seen and what may need retrying.


## Current state of the project

- The current production flow processes collections sequentially.
- It already performs collection discovery, download planning, downloading, fixity writing, and collection-level spreadsheet updates.
- The design plan still leaves room for a later concurrent version with dedicated download workers and a separate spreadsheet updater.


## FAQs

### store-time and lookback

- One of the first steps is determining which WARC files need download for each active collection listed in the tracking spreadsheet.

- WASAPI exposes several timestamps, including `crawl-start-time`, `crawl-time`, and `store-time`. This script uses only `store-time` for discovery and checkpointing.

- That choice is intentional: `store-time` reflects when the WARC is actually available in WASAPI, and it can be later than the crawl-related timestamps. Since this script is about backup tracking rather than crawl tracking, `store-time` is the safest single clock to follow.

- The per-collection local state stores one checkpoint value:
  - `enumeration_checkpoint_store_time_max` -- This is a bookmark for how far the script got in listing candidate files from WASAPI. 

- On each run, the script:
  - reads that saved checkpoint
  - subtracts 30 days from it
  - queries WASAPI with `store-time-after=<checkpoint minus 30 days>`

- On a first run, when no checkpoint exists yet, the script does a full historical backfill for that collection instead of limiting itself to only the last 30 days.

- Why keep the 30-day overlap window?

- The overlap protects against incomplete or interrupted enumeration and download work.

- Example:

  - a run sees files with `store-time` values of Feb-02, Feb-04, and Feb-06
  - the script successfully enumerates all three files
  - but a later step fails before every needed file is downloaded or before all local state is updated as intended

- If the next run queried only for files strictly after Feb-06, it could miss a file that should still be retried.

- By querying again from 30 days before the saved checkpoint, the script deliberately re-sees a recent slice of already-known records. That overlap is then made safe by local filename-based state and deduplication logic.

- In short, the 30-day window is a recovery buffer: it reduces the chance that a partial run or transient failure causes the script to permanently skip a WARC that should have been backed up.


---

### why is the local filesystem the source of truth?

- The script is meant to make safe backup decisions based on what is actually present on disk.

- The spreadsheet is useful for visibility, but it is not detailed enough to serve as the authoritative record of every file and retry state.

- By keeping the main truth locally, the script can recover more safely from interruptions, partial downloads, or spreadsheet write issues.

- In practice, that means the most important record of progress is the collection's local folder plus its `state.json` file.

- Just a note that this `state.json` file gets updated as each download attempt is made. So if a file fails to successfully download, even if the checkpoint/bookmark-date may move forward, subsequent runs will retry the failed downloads.

---

### what gets stored for each collection?

- Each collection gets its own local directory.

- That directory includes:
  - downloaded WARC files
  - fixity metadata files
  - a `state.json` file describing what the script has discovered and recorded for that collection

WARC and fixity files are stored by seed id:

```text
collections/<collection_id>/<seed_id>/<year>/<month>/<filename>
collections/<collection_id>/<seed_id>/<year>/<month>/<filename>.sha256
collections/<collection_id>/<seed_id>/<year>/<month>/<filename>.json
```

If a WARC filename does not include a parseable `SEED...` value, the file is stored under `UNKNOWN_SEED`. The `cron_scripts/check_for_unknown_seeds.py` script can be scheduled to report those files by email.

- This layout is meant to keep each collection self-contained and easier to inspect.

---

### spreadsheet updates

- The tracking spreadsheet is used as a reporting and control interface for collection-level backup activity.

- It helps an operator quickly see whether a collection is currently being checked, whether downloads are planned, whether there is nothing new to fetch, and what the final collection outcome was.

- The spreadsheet is **not** the source of truth for file correctness or retry logic.

- The local filesystem plus each collection's `state.json` remain authoritative for what has been discovered, downloaded, and recorded durably. These files can be viewed at `(server)/warc_downloads/collections/collection-ID/state.json`.

- In the current sequential flow, spreadsheet updates are written at a small number of collection-level checkpoints:
  - when discovery begins
  - after download planning completes
  - when no new files need download
  - when downloading begins
  - at coarse in-progress milestones during downloading
  - when final collection reporting is written

- The in-progress download updates are intentionally coarse rather than per-file chatter.

- `status-last-fetch` holds the coarse machine-readable status, such as `discovery-in-progress` or `downloading-in-progress`.

- `status-detail` holds the human-readable detail for that status, including discovery mode, no-new-files notes, final outcome details, and coarse download progress such as `40% (2/5 files)`.

- `status-last-fetch-file-count` holds the numeric count of WARC filename records returned by the latest WASAPI fetch.

- This keeps the sheet useful for monitoring without making spreadsheet state responsible for correctness.

---


## Current code module responsibilities

- `main.py` remains a thin entry point that loads config, configures logging, opens an authenticated `httpx.Client`, and iterates collection jobs.
- `lib/orchestration.py` processes collections sequentially.
- `lib/collection_sheet.py` loads active collection jobs from the spreadsheet.
- `lib/local_state.py` loads and saves `state.json` atomically and records durable[^durable] per-file download/fixity outcomes.
- `lib/wasapi_discovery.py` performs production WASAPI discovery with overlap-window checkpoint logic.
- `lib/storage_layout.py` derives seed/year/month partitions from WARC filenames and computes planned WARC/fixity destinations.
- `lib/downloader.py` streams WARC files, writes to `*.partial`, removes stale partial files on retry, and atomically renames successful downloads into place.
- `lib/fixity.py` computes SHA-256 and writes `.sha256` and `.json` fixity files for successfully downloaded WARCs.
- `cron_scripts/check_for_unknown_seeds.py` scans for WARC files under `UNKNOWN_SEED` folders and sends an email alert when any are found.

[^durable]: Here, durable means the recorded outcomes are meant to survive process exits, crashes, and later reruns because they are written into `state.json` on disk, not just kept in memory for the current execution.

---
