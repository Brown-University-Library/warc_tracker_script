import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from lib.collection_sheet import CollectionJob
from lib.downloader import DownloadResult, download_to_path
from lib.fixity import FixityResult, write_fixity_sidecars
from lib.local_state import load_collection_state, save_collection_state
from lib.storage_layout import PlannedCollectionPaths, StorageLayoutError, plan_collection_paths
from lib.wasapi_discovery import compute_store_time_after_datetime, fetch_collection_discovery

DEFAULT_STORAGE_ROOT: Path = Path(__file__).resolve().parent.parent / 'storage'

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlannedDownload:
    """
    Represents one discovered record that can be downloaded to a planned local path.
    """

    filename: str
    source_url: str
    planned_paths: PlannedCollectionPaths


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


def run_planned_downloads(
    client: httpx.Client,
    collection_id: int,
    planned_downloads: list[PlannedDownload],
) -> tuple[list[DownloadResult], list[FixityResult]]:
    """
    Downloads planned WARC files sequentially, generates fixity for successful downloads, and returns the per-file results.
    Called by: process_collection_job()
    """
    results: list[DownloadResult] = []
    fixity_results: list[FixityResult] = []
    for planned_download in planned_downloads:
        destination_path = planned_download.planned_paths.warc_path
        if destination_path.exists():
            log.info(
                'Collection %s skipping download for %s because the destination already exists: %s',
                collection_id,
                planned_download.filename,
                destination_path,
            )
            continue

        download_result = download_to_path(client, planned_download.source_url, destination_path)
        results.append(download_result)
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
    log.info('Collection %s spreadsheet progress updates are not implemented yet.', collection_job.collection_id)


def process_collection_job(
    client: httpx.Client,
    collection_job: CollectionJob,
    storage_root: Path,
    wasapi_base_url: str,
) -> None:
    """
    Processes one collection through the implemented sequential orchestration stages.
    Called by: run_collection_orchestration()
    """
    state = load_collection_state(storage_root, collection_job.collection_id)
    checkpoint_store_time_max = state.get('enumeration_checkpoint_store_time_max')
    checkpoint_value = checkpoint_store_time_max if isinstance(checkpoint_store_time_max, str) else None
    after_datetime = compute_store_time_after_datetime(checkpoint_value, datetime.now(UTC))

    log.info(
        'Processing collection %s with store-time-after boundary %s.',
        collection_job.collection_id,
        after_datetime.isoformat(),
    )

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
    planned_downloads = build_planned_downloads(storage_root, collection_job.collection_id, discovery_result.records)
    download_results, fixity_results = run_planned_downloads(client, collection_job.collection_id, planned_downloads)
    log_collection_download_summary(
        collection_job,
        pending_download_count,
        len(planned_downloads),
        download_results,
        fixity_results,
    )
