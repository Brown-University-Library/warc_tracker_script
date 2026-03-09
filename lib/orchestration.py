import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import gspread
import httpx

from lib.collection_sheet import (
    CollectionJob,
    CollectionProcessingStatusUpdate,
    CollectionSummaryUpdate,
    HeaderLocation,
    update_collection_final_reporting,
    update_collection_processing_status,
)
from lib.downloader import DownloadResult, download_to_path
from lib.fixity import FixityResult, validate_fixity_sidecars, write_fixity_sidecars
from lib.local_state import (
    load_collection_state,
    save_collection_state,
    update_file_manifest_for_download_result,
    update_file_manifest_for_fixity_result,
    update_file_manifest_for_planned_download,
)
from lib.storage_layout import PlannedCollectionPaths, StorageLayoutError, plan_collection_paths
from lib.wasapi_discovery import compute_store_time_after_datetime, fetch_collection_discovery

DEFAULT_STORAGE_ROOT: Path = Path(__file__).resolve().parent.parent / 'storage'

log = logging.getLogger(__name__)

STATUS_DISCOVERY_IN_PROGRESS = 'discovery-in-progress'
STATUS_DOWNLOAD_PLANNING_COMPLETE = 'download-planning-complete'
STATUS_DOWNLOADING_IN_PROGRESS = 'downloading-in-progress'
STATUS_NO_NEW_FILES_TO_DOWNLOAD = 'no-new-files-to-download'
STATUS_DOWNLOADED_WITHOUT_ERRORS = 'downloaded-without-errors'
STATUS_COMPLETED_WITH_SOME_FILE_FAILURES = 'completed-with-some-file-failures'
STATUS_DISCOVERY_FAILED = 'discovery-failed'
STATUS_SPREADSHEET_UPDATE_FAILED = 'spreadsheet-update-failed'
DISCOVERY_MODE_FULL_BACKFILL_FIRST_RUN = 'full-backfill-first-run'
DISCOVERY_MODE_INCREMENTAL_OVERLAP_WINDOW = 'incremental-overlap-window'

RUN_COORDINATION_MODE_CRON_LOCKED = 'cron_locked'
BLOCKING_COORDINATION_STATUSES = frozenset(
    (
        STATUS_DISCOVERY_IN_PROGRESS,
        STATUS_DOWNLOADING_IN_PROGRESS,
    )
)

DOWNLOAD_PROGRESS_MILESTONES = (20, 40, 60, 80)


class RunCoordinationError(RuntimeError):
    """
    Indicates that startup coordination policy refused to begin a non-cron_locked run.
    """


@dataclass(frozen=True)
class BlockingCoordinationSummary:
    """
    Represents blocking in-progress spreadsheet statuses found during startup preflight.
    """

    blocking_collection_ids: list[int]
    blocking_statuses: list[str]


def format_downloaded_size_gb(size_bytes: int) -> str:
    """
    Formats a byte count as gigabytes rounded to one decimal place.
    Called by: build_collection_summary_update()
    """
    size_gb = size_bytes / (1024**3)
    result = f'{size_gb:.1f} GB'
    return result


@dataclass(frozen=True)
class PlannedDownload:
    """
    Represents one discovered record that can be downloaded to a planned local path.
    """

    filename: str
    source_url: str
    planned_paths: PlannedCollectionPaths


@dataclass(frozen=True)
class CollectionProcessingReport:
    """
    Represents the final spreadsheet reporting values for one processed collection.
    """

    status_update: CollectionProcessingStatusUpdate
    summary_update: CollectionSummaryUpdate


def get_downloaded_storage_root() -> Path:
    """
    Returns the configured local storage root.
    Called by: process_collection_job()
    """
    configured_storage_root = os.getenv('WARC_STORAGE_ROOT')
    result = DEFAULT_STORAGE_ROOT
    if configured_storage_root:
        result = Path(configured_storage_root).expanduser()
    return result


def get_archive_it_credentials() -> tuple[str, str] | None:
    """
    Returns Archive-It credentials from the environment when available.
    Called by: process_collection_job()
    """
    username = os.getenv('ARCHIVEIT_WASAPI_USERNAME') or os.getenv('ARCHIVEIT_USER')
    password = os.getenv('ARCHIVEIT_WASAPI_PASSWORD') or os.getenv('ARCHIVEIT_PASS')
    result: tuple[str, str] | None = None
    if username and password:
        result = (username, password)
    return result


def get_run_coordination_mode() -> str | None:
    """
    Returns the configured startup coordination mode when present.
    Called by: run_collection_orchestration()
    """
    configured_mode = os.getenv('RUN_COORDINATION_MODE')
    result: str | None = None
    if configured_mode is not None:
        stripped_mode = configured_mode.strip()
        if stripped_mode:
            result = stripped_mode
    return result


def should_skip_spreadsheet_coordination_check(coordination_mode: str | None) -> bool:
    """
    Returns whether startup spreadsheet coordination preflight should be skipped.
    Called by: enforce_startup_run_coordination()
    """
    result = coordination_mode == RUN_COORDINATION_MODE_CRON_LOCKED
    return result


def get_blocking_coordination_summary(
    values: list[list[str]],
    header_location: HeaderLocation,
    collection_jobs: list[CollectionJob],
) -> BlockingCoordinationSummary | None:
    """
    Returns blocking in-progress spreadsheet statuses for the active collection-job surface.
    Called by: enforce_startup_run_coordination()
    """
    blocking_collection_ids: list[int] = []
    blocking_statuses: set[str] = set()
    status_column_index = header_location.column_map['processing_status_main']
    collection_jobs_by_row = {collection_job.row_number: collection_job for collection_job in collection_jobs}
    for row_number, collection_job in collection_jobs_by_row.items():
        row_index = row_number - 1
        if row_index < 0 or row_index >= len(values):
            continue
        row = values[row_index]
        status_value = ''
        if status_column_index < len(row):
            status_value = row[status_column_index].strip()
        if not status_value:
            continue
        normalized_status = status_value.casefold()
        if normalized_status in BLOCKING_COORDINATION_STATUSES:
            blocking_collection_ids.append(collection_job.collection_id)
            blocking_statuses.add(normalized_status)
        else:
            log.info(
                'Collection %s coordination preflight ignored non-blocking spreadsheet status %s.',
                collection_job.collection_id,
                status_value,
            )
    result: BlockingCoordinationSummary | None = None
    if blocking_collection_ids:
        result = BlockingCoordinationSummary(
            blocking_collection_ids=blocking_collection_ids,
            blocking_statuses=sorted(blocking_statuses),
        )
    return result


def enforce_startup_run_coordination(
    coordination_mode: str | None,
    values: list[list[str]],
    header_location: HeaderLocation,
    collection_jobs: list[CollectionJob],
) -> None:
    """
    Enforces the startup spreadsheet coordination policy for non-cron_locked runs.
    Called by: run_collection_orchestration()
    """
    log.info('Resolved startup coordination mode: %s', coordination_mode or '<unset>')
    if should_skip_spreadsheet_coordination_check(coordination_mode):
        log.info('Skipping spreadsheet coordination preflight because RUN_COORDINATION_MODE=cron_locked.')
        return
    blocking_summary = get_blocking_coordination_summary(values, header_location, collection_jobs)
    if blocking_summary is None:
        log.info('Spreadsheet coordination preflight found no blocking in-progress statuses.')
        return
    log.error(
        'Spreadsheet coordination preflight blocked startup with %s blocking rows and statuses %s.',
        len(blocking_summary.blocking_collection_ids),
        blocking_summary.blocking_statuses,
    )
    blocking_collection_id_display = ', '.join(
        str(collection_id) for collection_id in blocking_summary.blocking_collection_ids
    )
    blocking_status_display = ', '.join(blocking_summary.blocking_statuses)
    raise RunCoordinationError(
        'Non-cron_locked runs must not start when spreadsheet in-progress statuses are present. '
        f'Blocking statuses: {blocking_status_display}. '
        f'Blocking collection ids: {blocking_collection_id_display}.'
    )


def count_pending_download_candidates(discovered_records: list[dict[str, object]], state: dict[str, object]) -> int:
    """
    Counts discovered records that do not yet have a downloaded status in local state.
    Called by: process_collection_job()
    """
    files_state = state.get('files')
    known_files = files_state if isinstance(files_state, dict) else {}
    pending_count = 0
    for record in discovered_records:
        filename_value = record.get('filename')
        if not isinstance(filename_value, str) or not filename_value.strip():
            continue
        file_state = known_files.get(filename_value)
        if not isinstance(file_state, dict) or file_state.get('status') != 'downloaded':
            pending_count += 1
    result = pending_count
    return result


def build_planned_download_paths(
    storage_root: Path,
    collection_id: int,
    discovered_records: list[dict[str, object]],
) -> list[PlannedCollectionPaths]:
    """
    Builds planned local WARC and fixity destinations for discovered records with usable filenames.
    Called by: process_collection_job()
    """
    planned_paths: list[PlannedCollectionPaths] = []
    for record in discovered_records:
        filename_value = record.get('filename')
        if not isinstance(filename_value, str) or not filename_value.strip():
            continue
        try:
            planned_paths.append(plan_collection_paths(storage_root, collection_id, filename_value))
        except StorageLayoutError:
            log.exception(
                'Collection %s record filename could not be mapped to the local storage layout: %s',
                collection_id,
                filename_value,
            )
    result = planned_paths
    return result


def get_record_source_url(record: dict[str, object]) -> str | None:
    """
    Returns the first usable download URL from one discovered record.
    Called by: build_planned_downloads()
    """
    url_candidates: list[object] = []
    locations_value = record.get('locations')
    if isinstance(locations_value, list):
        url_candidates.extend(locations_value)

    for field_name in ('location', 'url'):
        field_value = record.get(field_name)
        if field_value is not None:
            url_candidates.append(field_value)

    result: str | None = None
    for candidate in url_candidates:
        if isinstance(candidate, str) and candidate.strip():
            result = candidate.strip()
            break
    return result


def build_planned_downloads(
    storage_root: Path,
    collection_id: int,
    discovered_records: list[dict[str, object]],
) -> list[PlannedDownload]:
    """
    Builds planned download inputs for records that have both a usable filename and source URL.
    Called by: process_collection_job()
    """
    result: list[PlannedDownload] = []
    for record in discovered_records:
        filename_value = record.get('filename')
        if not isinstance(filename_value, str) or not filename_value.strip():
            continue

        source_url = get_record_source_url(record)
        if source_url is None:
            log.info(
                'Collection %s skipping record %s because no usable source URL was present.',
                collection_id,
                filename_value,
            )
            continue

        try:
            planned_paths = plan_collection_paths(storage_root, collection_id, filename_value)
        except StorageLayoutError:
            log.exception(
                'Collection %s record filename could not be mapped to the local storage layout: %s',
                collection_id,
                filename_value,
            )
            continue

        result.append(
            PlannedDownload(
                filename=filename_value,
                source_url=source_url,
                planned_paths=planned_paths,
            )
        )
    return result


def build_reconciliation_retry_downloads(
    storage_root: Path,
    collection_id: int,
    state: dict[str, object],
) -> list[PlannedDownload]:
    """
    Builds retry candidates from manifest entries whose expected WARC file is absent on disk.
    Called by: process_collection_job()
    """
    result: list[PlannedDownload] = []
    files_value = state.get('files')
    files_state = files_value if isinstance(files_value, dict) else {}
    for filename_key, entry_value in files_state.items():
        if not isinstance(filename_key, str) or not filename_key.strip():
            continue
        if not isinstance(entry_value, dict):
            continue

        source_url_value = entry_value.get('source_url')
        warc_path_value = entry_value.get('warc_path')
        if not isinstance(source_url_value, str) or not source_url_value.strip():
            continue
        if not isinstance(warc_path_value, str) or not warc_path_value.strip():
            continue
        if Path(warc_path_value).exists():
            continue

        try:
            planned_paths = plan_collection_paths(storage_root, collection_id, filename_key)
        except StorageLayoutError:
            log.exception(
                'Collection %s manifest filename could not be mapped to the local storage layout: %s',
                collection_id,
                filename_key,
            )
            continue

        result.append(
            PlannedDownload(
                filename=filename_key,
                source_url=source_url_value.strip(),
                planned_paths=planned_paths,
            )
        )
    return result


def merge_planned_downloads(
    reconciliation_downloads: list[PlannedDownload],
    discovery_downloads: list[PlannedDownload],
) -> list[PlannedDownload]:
    """
    Merges reconciliation and discovery planned downloads, preferring discovery when filenames overlap.
    Called by: process_collection_job()
    """
    merged_by_filename: dict[str, PlannedDownload] = {}
    for planned_download in reconciliation_downloads:
        merged_by_filename[planned_download.filename] = planned_download
    for planned_download in discovery_downloads:
        merged_by_filename[planned_download.filename] = planned_download
    result = list(merged_by_filename.values())
    return result


def log_planned_download_candidate_counts(
    collection_id: int,
    reconciliation_count: int,
    discovery_count: int,
    merged_count: int,
) -> None:
    """
    Logs the counts of reconciliation, discovery, and merged planned download candidates.
    Called by: process_collection_job()
    """
    log.info(
        'Collection %s has %s reconciliation candidates, %s discovery candidates, and %s merged planned downloads.',
        collection_id,
        reconciliation_count,
        discovery_count,
        merged_count,
    )


def log_planned_download_paths(collection_id: int, planned_paths: list[PlannedCollectionPaths]) -> None:
    """
    Logs the planned local WARC and fixity destinations for discovered records.
    Called by: process_collection_job()
    """
    for planned_path in planned_paths:
        log.info(
            'Collection %s planned paths for %s: warc=%s sha256=%s json=%s',
            collection_id,
            planned_path.filename,
            planned_path.warc_path,
            planned_path.sha256_path,
            planned_path.json_path,
        )


def save_collection_state_after_file_processing(
    storage_root: Path,
    collection_id: int,
    state: dict[str, object],
    filename: str,
) -> None:
    """
    Saves collection state after one file outcome has been recorded durably.
    Called by: run_planned_downloads()
    """
    save_collection_state(storage_root, collection_id, state)
    log.info('Saved collection %s state after processing %s.', collection_id, filename)


def persist_planned_downloads_to_state(
    storage_root: Path,
    collection_id: int,
    state: dict[str, object],
    planned_downloads: list[PlannedDownload],
    discovered_at: str,
) -> None:
    """
    Persists planned-download manifest entries before the download loop begins.
    Called by: process_collection_job()
    """
    if not planned_downloads:
        return

    for planned_download in planned_downloads:
        update_file_manifest_for_planned_download(
            state=state,
            filename=planned_download.filename,
            source_url=planned_download.source_url,
            warc_path=planned_download.planned_paths.warc_path,
            discovered_at=discovered_at,
        )
    save_collection_state(storage_root, collection_id, state)
    log.info(
        'Saved collection %s state with %s planned download entries before downloads begin.',
        collection_id,
        len(planned_downloads),
    )


def build_collection_status_update(status_main: str, status_detail: str) -> CollectionProcessingStatusUpdate:
    """
    Builds a collection-level processing status payload.
    Called by: write_collection_start_status()
    """
    result = CollectionProcessingStatusUpdate(
        processing_status_main=status_main,
        processing_status_detail=status_detail,
    )
    return result


def write_collection_status_update(
    worksheet: gspread.Worksheet,
    header_location: HeaderLocation,
    collection_job: CollectionJob,
    status_update: CollectionProcessingStatusUpdate,
) -> None:
    """
    Writes one collection-level processing status update to the spreadsheet.
    Called by: write_collection_start_status()
    """
    update_collection_processing_status(worksheet, header_location, collection_job.row_number, status_update)


def build_download_planning_status(planned_download_count: int) -> CollectionProcessingStatusUpdate:
    """
    Builds the collection-level status update written after download planning completes.
    Called by: write_collection_download_planning_status()
    """
    result = build_collection_status_update(
        STATUS_DOWNLOAD_PLANNING_COMPLETE,
        f'{planned_download_count} files planned',
    )
    return result


def build_no_new_files_status(discovery_completed_at: str) -> CollectionProcessingStatusUpdate:
    """
    Builds the collection-level status update written when no downloads are needed.
    Called by: write_collection_no_new_files_status()
    """
    result = build_collection_status_update(
        STATUS_NO_NEW_FILES_TO_DOWNLOAD,
        f'since {discovery_completed_at}',
    )
    return result


def build_download_start_status(total_planned_downloads: int) -> CollectionProcessingStatusUpdate:
    """
    Builds the initial collection-level download-in-progress status update.
    Called by: write_collection_download_start_status()
    """
    result = build_collection_status_update(
        STATUS_DOWNLOADING_IN_PROGRESS,
        f'0% (0/{total_planned_downloads} files)',
    )
    return result


def build_download_progress_detail(percent_complete: int, completed_count: int, total_count: int) -> str:
    """
    Builds compact progress-detail text for one download milestone.
    Called by: get_download_progress_milestone_update()
    """
    result = f'{percent_complete}% ({completed_count}/{total_count} files)'
    return result


def get_download_progress_milestone_update(
    total_count: int,
    completed_count: int,
    last_reported_percent: int,
) -> tuple[int, str | None]:
    """
    Returns the next coarse progress milestone text, if a new milestone has been reached.
    Called by: run_planned_downloads()
    """
    next_reported_percent = last_reported_percent
    progress_detail: str | None = None
    if total_count > 0 and completed_count < total_count:
        percent_complete = (completed_count * 100) // total_count
        for milestone_percent in DOWNLOAD_PROGRESS_MILESTONES:
            if percent_complete >= milestone_percent and milestone_percent > last_reported_percent:
                next_reported_percent = milestone_percent
                progress_detail = build_download_progress_detail(
                    milestone_percent,
                    completed_count,
                    total_count,
                )
    result = (next_reported_percent, progress_detail)
    return result


def run_planned_downloads(
    client: httpx.Client,
    storage_root: Path,
    collection_id: int,
    state: dict[str, object],
    planned_downloads: list[PlannedDownload],
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[list[DownloadResult], list[FixityResult]]:
    """
    Downloads planned WARC files sequentially, generates fixity for successful downloads, and returns the per-file results.
    Called by: process_collection_job()
    """
    results: list[DownloadResult] = []
    fixity_results: list[FixityResult] = []
    last_reported_percent = 0
    total_planned_downloads = len(planned_downloads)
    for planned_download in planned_downloads:
        destination_path = planned_download.planned_paths.warc_path
        if destination_path.exists():
            log.info(
                'Collection %s skipping download for %s because the destination already exists and proceeding to fixity handling: %s',
                collection_id,
                planned_download.filename,
                destination_path,
            )
            fixity_result = write_fixity_sidecars(
                warc_path=destination_path,
                sha256_path=planned_download.planned_paths.sha256_path,
                json_path=planned_download.planned_paths.json_path,
                source_url=planned_download.source_url,
            )
            fixity_results.append(fixity_result)
            update_file_manifest_for_fixity_result(
                state=state,
                filename=planned_download.filename,
                sha256_path=planned_download.planned_paths.sha256_path,
                json_path=planned_download.planned_paths.json_path,
                success=fixity_result.success,
                completed_at=fixity_result.completed_at,
                error_message=fixity_result.error_message,
            )
            save_collection_state_after_file_processing(storage_root, collection_id, state, planned_download.filename)
            if fixity_result.success:
                log.info(
                    'Collection %s repaired or refreshed fixity sidecars for %s: sha256=%s json=%s',
                    collection_id,
                    planned_download.filename,
                    fixity_result.sha256_path,
                    fixity_result.json_path,
                )
            else:
                log.error(
                    'Collection %s fixity repair failed for %s: %s',
                    collection_id,
                    planned_download.filename,
                    fixity_result.error_message,
                )
            continue

        log.debug(
            'Collection ``%s`` about to download ``%s`` from ``%s`` to ``%s``',
            collection_id,
            planned_download.filename,
            planned_download.source_url,
            destination_path,
        )
        download_result = download_to_path(client, planned_download.source_url, destination_path)
        results.append(download_result)
        update_file_manifest_for_download_result(
            state=state,
            filename=planned_download.filename,
            source_url=planned_download.source_url,
            warc_path=destination_path,
            success=download_result.success,
            error_message=download_result.error_message,
        )
        save_collection_state_after_file_processing(storage_root, collection_id, state, planned_download.filename)
        if download_result.success:
            log.info(
                'Collection %s downloaded %s bytes for %s to %s',
                collection_id,
                download_result.bytes_written,
                planned_download.filename,
                download_result.destination_path,
            )
            fixity_result = write_fixity_sidecars(
                warc_path=download_result.destination_path,
                sha256_path=planned_download.planned_paths.sha256_path,
                json_path=planned_download.planned_paths.json_path,
                source_url=planned_download.source_url,
            )
            fixity_results.append(fixity_result)
            update_file_manifest_for_fixity_result(
                state=state,
                filename=planned_download.filename,
                sha256_path=planned_download.planned_paths.sha256_path,
                json_path=planned_download.planned_paths.json_path,
                success=fixity_result.success,
                completed_at=fixity_result.completed_at,
                error_message=fixity_result.error_message,
            )
            save_collection_state_after_file_processing(storage_root, collection_id, state, planned_download.filename)
            if fixity_result.success:
                log.info(
                    'Collection %s wrote fixity sidecars for %s: sha256=%s json=%s',
                    collection_id,
                    planned_download.filename,
                    fixity_result.sha256_path,
                    fixity_result.json_path,
                )
            else:
                log.error(
                    'Collection %s fixity writing failed for %s: %s',
                    collection_id,
                    planned_download.filename,
                    fixity_result.error_message,
                )
        else:
            log.error(
                'Collection %s download failed for %s from %s: %s',
                collection_id,
                planned_download.filename,
                planned_download.source_url,
                download_result.error_message,
            )
        completed_count = len(results)
        last_reported_percent, progress_detail = get_download_progress_milestone_update(
            total_planned_downloads,
            completed_count,
            last_reported_percent,
        )
        if progress_detail is not None and progress_callback is not None:
            log.info('Collection %s wrote download progress milestone: %s', collection_id, progress_detail)
            progress_callback(progress_detail)
    result = (results, fixity_results)
    return result


def log_collection_download_summary(
    collection_job: CollectionJob,
    pending_download_count: int,
    planned_download_count: int,
    download_results: list[DownloadResult],
    fixity_results: list[FixityResult],
) -> None:
    """
    Logs a summary of download activity for one collection.
    Called by: process_collection_job()
    """
    success_count = sum(1 for result in download_results if result.success)
    failure_count = sum(1 for result in download_results if not result.success)
    skipped_count = planned_download_count - len(download_results)
    fixity_success_count = sum(1 for result in fixity_results if result.success)
    fixity_failure_count = sum(1 for result in fixity_results if not result.success)
    log.info(
        'Collection %s has %s pending candidates, %s planned downloads, %s download successes, %s download failures, %s skipped existing files, %s fixity successes, and %s fixity failures.',
        collection_job.collection_id,
        pending_download_count,
        planned_download_count,
        success_count,
        failure_count,
        skipped_count,
        fixity_success_count,
        fixity_failure_count,
    )


def iter_collection_warc_paths(storage_root: Path, collection_id: int) -> list[Path]:
    """
    Returns downloaded WARC paths currently present on disk for one collection.
    Called by: get_collection_downloaded_totals()
    """
    collection_root = storage_root / 'collections' / str(collection_id)
    warc_root = collection_root / 'warcs'
    result: list[Path] = []
    if warc_root.exists():
        result = [path for path in warc_root.rglob('*.warc.gz') if path.is_file()]
    return result


def get_collection_downloaded_totals(storage_root: Path, collection_id: int) -> tuple[int, int]:
    """
    Returns the total downloaded WARC count and byte size currently present for one collection.
    Called by: build_collection_summary_update()
    """
    warc_paths = iter_collection_warc_paths(storage_root, collection_id)
    total_count = len(warc_paths)
    total_size = sum(path.stat().st_size for path in warc_paths)
    log.info(
        'Collection %s final summary totals computed from on-disk WARCs: %s files, %s bytes.',
        collection_id,
        total_count,
        total_size,
    )
    result = (total_count, total_size)
    return result


def build_collection_summary_update(
    storage_root: Path,
    collection_id: int,
    discovery_completed_at: str,
) -> CollectionSummaryUpdate:
    """
    Builds final spreadsheet summary-field values for one collection.
    Called by: build_collection_final_report()
    """
    collection_root = storage_root / 'collections' / str(collection_id)
    total_downloaded_count, total_downloaded_size = get_collection_downloaded_totals(storage_root, collection_id)
    result = CollectionSummaryUpdate(
        summary_status_last_wasapi_check=discovery_completed_at,
        summary_status_downloaded_warcs_count=str(total_downloaded_count),
        summary_status_downloaded_warcs_size=format_downloaded_size_gb(total_downloaded_size),
        summary_status_server_path=str(collection_root),
    )
    return result


def build_collection_final_report(
    storage_root: Path,
    collection_job: CollectionJob,
    discovery_completed_at: str,
    planned_downloads: list[PlannedDownload],
    download_results: list[DownloadResult],
    fixity_results: list[FixityResult],
) -> CollectionProcessingReport:
    """
    Builds the final collection status and summary payload for spreadsheet reporting.
    Called by: process_collection_job()
    """
    failure_count = sum(1 for result in download_results if not result.success)
    failure_count += sum(1 for result in fixity_results if not result.success)
    successful_download_count = sum(1 for result in download_results if result.success)
    status_main = STATUS_DOWNLOADED_WITHOUT_ERRORS
    status_detail = f'{successful_download_count} file downloads completed successfully'
    if not planned_downloads:
        status_main = STATUS_NO_NEW_FILES_TO_DOWNLOAD
        status_detail = f'since {discovery_completed_at}'
    elif failure_count > 0:
        status_main = STATUS_COMPLETED_WITH_SOME_FILE_FAILURES
        status_detail = f'{failure_count} file operations failed'
    result = CollectionProcessingReport(
        status_update=CollectionProcessingStatusUpdate(
            processing_status_main=status_main,
            processing_status_detail=status_detail,
        ),
        summary_update=build_collection_summary_update(
            storage_root=storage_root,
            collection_id=collection_job.collection_id,
            discovery_completed_at=discovery_completed_at,
        ),
    )
    return result


def build_collection_failure_report(
    storage_root: Path,
    collection_job: CollectionJob,
    status_main: str,
    status_detail: str,
    reported_at: str,
) -> CollectionProcessingReport:
    """
    Builds a failure-oriented spreadsheet report for collection-level processing exceptions.
    Called by: run_collection_orchestration()
    """
    result = CollectionProcessingReport(
        status_update=CollectionProcessingStatusUpdate(
            processing_status_main=status_main,
            processing_status_detail=status_detail,
        ),
        summary_update=CollectionSummaryUpdate(
            summary_status_last_wasapi_check=reported_at,
            summary_status_downloaded_warcs_count='0',
            summary_status_downloaded_warcs_size='0.0 GB',
            summary_status_server_path=str(storage_root / 'collections' / str(collection_job.collection_id)),
        ),
    )
    return result


def determine_collection_discovery_mode(
    checkpoint_store_time_max: str | None,
    now: datetime,
) -> tuple[str, datetime | None]:
    """
    Determines the collection discovery mode and optional store-time-after boundary.
    Called by: process_collection_job()
    """
    discovery_mode = DISCOVERY_MODE_FULL_BACKFILL_FIRST_RUN
    after_datetime: datetime | None = None
    if checkpoint_store_time_max is not None:
        discovery_mode = DISCOVERY_MODE_INCREMENTAL_OVERLAP_WINDOW
        after_datetime = compute_store_time_after_datetime(checkpoint_store_time_max, now)
    result = (discovery_mode, after_datetime)
    return result


def write_collection_start_status(
    worksheet: gspread.Worksheet,
    header_location: HeaderLocation,
    collection_job: CollectionJob,
    discovery_mode: str,
    after_datetime: datetime | None,
) -> None:
    """
    Writes the collection-level start status before discovery begins.
    Called by: process_collection_job()
    """
    status_detail = 'full historical backfill'
    if discovery_mode == DISCOVERY_MODE_INCREMENTAL_OVERLAP_WINDOW and after_datetime is not None:
        status_detail = f'store-time-after {after_datetime.isoformat()}'
    status_update = build_collection_status_update(STATUS_DISCOVERY_IN_PROGRESS, status_detail)
    write_collection_status_update(worksheet, header_location, collection_job, status_update)


def write_collection_download_planning_status(
    worksheet: gspread.Worksheet,
    header_location: HeaderLocation,
    collection_job: CollectionJob,
    planned_download_count: int,
) -> None:
    """
    Writes the collection-level status after download planning completes.
    Called by: process_collection_job()
    """
    status_update = build_download_planning_status(planned_download_count)
    write_collection_status_update(worksheet, header_location, collection_job, status_update)


def write_collection_no_new_files_status(
    worksheet: gspread.Worksheet,
    header_location: HeaderLocation,
    collection_job: CollectionJob,
    discovery_completed_at: str,
) -> None:
    """
    Writes the collection-level status for a no-op collection after planning.
    Called by: process_collection_job()
    """
    status_update = build_no_new_files_status(discovery_completed_at)
    write_collection_status_update(worksheet, header_location, collection_job, status_update)


def write_collection_download_start_status(
    worksheet: gspread.Worksheet,
    header_location: HeaderLocation,
    collection_job: CollectionJob,
    total_planned_downloads: int,
) -> None:
    """
    Writes the collection-level status when sequential downloading begins.
    Called by: process_collection_job()
    """
    status_update = build_download_start_status(total_planned_downloads)
    write_collection_status_update(worksheet, header_location, collection_job, status_update)


def write_collection_download_progress_status(
    worksheet: gspread.Worksheet,
    header_location: HeaderLocation,
    collection_job: CollectionJob,
    progress_detail: str,
) -> None:
    """
    Writes one coarse collection-level download progress milestone.
    Called by: process_collection_job.<lambda>()
    """
    status_update = build_collection_status_update(STATUS_DOWNLOADING_IN_PROGRESS, progress_detail)
    write_collection_status_update(worksheet, header_location, collection_job, status_update)


def write_collection_final_report(
    worksheet: gspread.Worksheet,
    header_location: HeaderLocation,
    collection_job: CollectionJob,
    report: CollectionProcessingReport,
) -> None:
    """
    Writes the final collection-level status and summary fields.
    Called by: process_collection_job()
    """
    update_collection_final_reporting(
        worksheet,
        header_location,
        collection_job.row_number,
        report.status_update,
        report.summary_update,
    )


def process_collection_job(
    client: httpx.Client,
    collection_job: CollectionJob,
    storage_root: Path,
    wasapi_base_url: str,
    worksheet: gspread.Worksheet,
    header_location: HeaderLocation,
) -> CollectionProcessingReport:
    """
    Processes one collection through the implemented sequential orchestration stages and returns final reporting values.
    Called by: run_collection_orchestration()
    """
    state = load_collection_state(storage_root, collection_job.collection_id)
    checkpoint_store_time_max = state.get('enumeration_checkpoint_store_time_max')
    checkpoint_value = checkpoint_store_time_max if isinstance(checkpoint_store_time_max, str) else None
    discovery_mode, after_datetime = determine_collection_discovery_mode(checkpoint_value, datetime.now(UTC))

    if after_datetime is None:
        log.info(
            'Processing collection %s in %s mode with no store-time-after boundary.',
            collection_job.collection_id,
            discovery_mode,
        )
    else:
        log.info(
            'Processing collection %s in %s mode with store-time-after boundary %s.',
            collection_job.collection_id,
            discovery_mode,
            after_datetime.isoformat(),
        )

    write_collection_start_status(worksheet, header_location, collection_job, discovery_mode, after_datetime)
    log.info('Collection %s spreadsheet status updated: discovery in progress.', collection_job.collection_id)

    discovery_result = fetch_collection_discovery(
        client=client,
        base_url=wasapi_base_url,
        collection_id=collection_job.collection_id,
        after_datetime=after_datetime,
    )
    log.info(
        'Collection %s discovery returned %s records across %s requests.',
        collection_job.collection_id,
        len(discovery_result.records),
        len(discovery_result.request_records),
    )

    if discovery_result.completed_successfully:
        state['enumeration_checkpoint_store_time_max'] = discovery_result.max_observed_store_time
        save_collection_state(storage_root, collection_job.collection_id, state)
        log.info(
            'Saved collection %s state with checkpoint %s.',
            collection_job.collection_id,
            discovery_result.max_observed_store_time,
        )

    pending_download_count = count_pending_download_candidates(discovery_result.records, state)
    planned_paths = build_planned_download_paths(storage_root, collection_job.collection_id, discovery_result.records)
    log_planned_download_paths(collection_job.collection_id, planned_paths)
    discovery_planned_downloads = build_planned_downloads(
        storage_root,
        collection_job.collection_id,
        discovery_result.records,
    )
    reconciliation_planned_downloads = build_reconciliation_retry_downloads(
        storage_root,
        collection_job.collection_id,
        state,
    )
    planned_downloads = merge_planned_downloads(
        reconciliation_planned_downloads,
        discovery_planned_downloads,
    )
    log_planned_download_candidate_counts(
        collection_job.collection_id,
        len(reconciliation_planned_downloads),
        len(discovery_planned_downloads),
        len(planned_downloads),
    )
    active_downloads, evaluation_reason_counts = build_evaluated_active_downloads(planned_downloads, state)
    log_active_download_evaluation_counts(
        collection_job.collection_id,
        len(planned_downloads),
        len(active_downloads),
        evaluation_reason_counts,
    )
    persist_planned_downloads_to_state(
        storage_root=storage_root,
        collection_id=collection_job.collection_id,
        state=state,
        planned_downloads=active_downloads,
        discovered_at=datetime.now(UTC).isoformat(),
    )
    write_collection_download_planning_status(
        worksheet,
        header_location,
        collection_job,
        len(active_downloads),
    )
    log.info(
        'Collection %s spreadsheet status updated: download planning complete with %s files planned.',
        collection_job.collection_id,
        len(active_downloads),
    )
    if not active_downloads:
        discovery_completed_at = datetime.now(UTC).isoformat()
        write_collection_no_new_files_status(
            worksheet,
            header_location,
            collection_job,
            discovery_completed_at,
        )
        log.info('Collection %s spreadsheet status updated: no new files to download.', collection_job.collection_id)
    else:
        write_collection_download_start_status(
            worksheet,
            header_location,
            collection_job,
            len(active_downloads),
        )
        log.info(
            'Collection %s spreadsheet status updated: downloading in progress for %s planned files.',
            collection_job.collection_id,
            len(active_downloads),
        )
    download_results, fixity_results = run_planned_downloads(
        client,
        storage_root,
        collection_job.collection_id,
        state,
        active_downloads,
        lambda progress_detail: write_collection_download_progress_status(
            worksheet,
            header_location,
            collection_job,
            progress_detail,
        ),
    )
    log_collection_download_summary(
        collection_job,
        pending_download_count,
        len(active_downloads),
        download_results,
        fixity_results,
    )
    result = build_collection_final_report(
        storage_root=storage_root,
        collection_job=collection_job,
        discovery_completed_at=datetime.now(UTC).isoformat(),
        planned_downloads=active_downloads,
        download_results=download_results,
        fixity_results=fixity_results,
    )
    write_collection_final_report(worksheet, header_location, collection_job, result)
    log.info('Collection %s spreadsheet status updated: final outcome written.', collection_job.collection_id)
    return result


@dataclass(frozen=True)
class DownloadNeedEvaluation:
    """
    Represents whether a planned candidate still requires backup work.
    """

    needs_work: bool
    reason: str


def get_manifest_expected_size(state: dict[str, object], filename: str) -> int | None:
    """
    Returns the expected size for one filename when current manifest data provides it.
    Called by: evaluate_planned_download_need()
    """
    files_value = state.get('files')
    files_state = files_value if isinstance(files_value, dict) else {}
    entry_value = files_state.get(filename)
    result: int | None = None
    if isinstance(entry_value, dict):
        size_value = entry_value.get('size')
        if isinstance(size_value, int):
            result = size_value
        else:
            json_path_value = entry_value.get('json_path')
            if isinstance(json_path_value, str) and json_path_value.strip():
                try:
                    json_data = json.loads(Path(json_path_value).read_text(encoding='utf-8'))
                    json_size_value = json_data.get('size') if isinstance(json_data, dict) else None
                    if isinstance(json_size_value, int):
                        result = json_size_value
                except Exception:
                    result = None
    return result


def evaluate_planned_download_need(
    planned_download: PlannedDownload,
    state: dict[str, object],
) -> DownloadNeedEvaluation:
    """
    Evaluates whether one planned candidate still requires backup work now.
    Called by: build_evaluated_active_downloads()
    """
    warc_path = planned_download.planned_paths.warc_path
    if not warc_path.exists():
        return DownloadNeedEvaluation(needs_work=True, reason='missing_warc')

    expected_size = get_manifest_expected_size(state, planned_download.filename)
    if expected_size is not None and warc_path.stat().st_size != expected_size:
        return DownloadNeedEvaluation(needs_work=True, reason='size_mismatch')

    fixity_validation = validate_fixity_sidecars(
        warc_path=warc_path,
        sha256_path=planned_download.planned_paths.sha256_path,
        json_path=planned_download.planned_paths.json_path,
    )
    if not fixity_validation.is_valid:
        reason = fixity_validation.error_reason or 'invalid_fixity'
        return DownloadNeedEvaluation(needs_work=True, reason=reason)

    files_value = state.get('files')
    files_state = files_value if isinstance(files_value, dict) else {}
    entry_value = files_state.get(planned_download.filename)
    if isinstance(entry_value, dict) and entry_value.get('status') == 'failed':
        return DownloadNeedEvaluation(needs_work=True, reason='retry_after_prior_failure')

    return DownloadNeedEvaluation(needs_work=False, reason='already_complete')


def build_evaluated_active_downloads(
    planned_downloads: list[PlannedDownload],
    state: dict[str, object],
) -> tuple[list[PlannedDownload], dict[str, int]]:
    """
    Builds the evaluated active-download list and a summary of evaluation reasons.
    Called by: process_collection_job()
    """
    active_downloads: list[PlannedDownload] = []
    reason_counts: dict[str, int] = {}
    for planned_download in planned_downloads:
        evaluation = evaluate_planned_download_need(planned_download, state)
        reason_counts[evaluation.reason] = reason_counts.get(evaluation.reason, 0) + 1
        if evaluation.needs_work:
            active_downloads.append(planned_download)
    result = (active_downloads, reason_counts)
    return result


def log_active_download_evaluation_counts(
    collection_id: int,
    merged_count: int,
    active_count: int,
    reason_counts: dict[str, int],
) -> None:
    """
    Logs the merged-versus-evaluated planning counts and evaluation reasons.
    Called by: process_collection_job()
    """
    log.info(
        'Collection %s evaluation kept %s of %s merged candidates as active downloads. Reason counts: %s',
        collection_id,
        active_count,
        merged_count,
        reason_counts,
    )
