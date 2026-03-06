import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

from lib.collection_sheet import CollectionJob, fetch_collection_jobs
from lib.local_state import load_collection_state, save_collection_state
from lib.wasapi_discovery import WasapiDiscoveryError, compute_store_time_after_datetime, fetch_collection_discovery

DEFAULT_STORAGE_ROOT: Path = Path(__file__).resolve().parent.parent / 'storage'

log = logging.getLogger(__name__)


def get_storage_root() -> Path:
    """
    Returns the configured local storage root.
    """
    configured_storage_root = os.getenv('WARC_STORAGE_ROOT')
    result = DEFAULT_STORAGE_ROOT
    if configured_storage_root:
        result = Path(configured_storage_root).expanduser()
    return result


def get_archive_it_credentials() -> tuple[str, str] | None:
    """
    Returns Archive-It credentials from the environment when available.
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


def log_not_yet_implemented_stages(collection_job: CollectionJob, pending_download_count: int) -> None:
    """
    Logs the planned but not-yet-implemented stages for one collection.
    """
    log.info(
        'Collection %s has %s pending download candidates; download queue submission is not implemented yet.',
        collection_job.collection_id,
        pending_download_count,
    )
    log.info(
        'Collection %s spreadsheet progress updates are not implemented yet.',
        collection_job.collection_id,
    )


def process_collection_job(
    client: httpx.Client,
    collection_job: CollectionJob,
    storage_root: Path,
    wasapi_base_url: str,
) -> None:
    """
    Processes one collection through the implemented sequential orchestration stages.
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
    log_not_yet_implemented_stages(collection_job, pending_download_count)


def run_collection_orchestration(
    spreadsheet_id: str,
    storage_root: Path,
    wasapi_base_url: str,
    archive_it_credentials: tuple[str, str],
) -> None:
    """
    Runs the current sequential collection orchestration flow.
    """
    collection_jobs = fetch_collection_jobs(spreadsheet_id)
    log.info('Active collections found: %s', len(collection_jobs))

    timeout = httpx.Timeout(30.0, connect=30.0)
    with httpx.Client(auth=archive_it_credentials, timeout=timeout, follow_redirects=True) as client:
        for collection_job in collection_jobs:
            try:
                process_collection_job(client, collection_job, storage_root, wasapi_base_url)
            except WasapiDiscoveryError as exc:
                partial_result = exc.partial_result
                partial_record_count = 0 if partial_result is None else len(partial_result.records)
                log.exception(
                    'Collection %s discovery failed after %s partial records.',
                    collection_job.collection_id,
                    partial_record_count,
                )
            except Exception:
                log.exception('Collection %s processing failed.', collection_job.collection_id)
