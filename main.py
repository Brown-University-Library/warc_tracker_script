import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import dotenv
import httpx

from lib.collection_sheet import CollectionSheetContractError, load_collection_sheet_context
from lib.orchestration import (
    STATUS_DISCOVERY_FAILED,
    STATUS_SPREADSHEET_UPDATE_FAILED,
    RunCoordinationError,
    build_collection_failure_report,
    enforce_startup_run_coordination,
    get_archive_it_credentials,
    get_downloaded_storage_root,
    get_run_coordination_mode,
    process_collection_job,
    write_collection_final_report,
)
from lib.wasapi_discovery import DEFAULT_WASAPI_BASE_URL, WasapiDiscoveryError

dotenv.load_dotenv()


LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE_PATH: Path = Path(os.environ['LOG_PATH'])

## setup logging
log_level = getattr(logging, LOG_LEVEL)  # maps the string name to the corresponding logging level constant
LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=log_level,
    format='[%(asctime)s] %(levelname)s [%(module)s-%(funcName)s()::%(lineno)d] %(message)s',
    datefmt='%d/%b/%Y %H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE_PATH),
    ],
)
log = logging.getLogger(__name__)

## prevent httpx from logging
if log_level <= logging.INFO:
    for noisy in ('httpx', 'httpcore'):
        lg = logging.getLogger(noisy)
        lg.setLevel(logging.WARNING)  # or logging.ERROR if you prefer only errors
        lg.propagate = False  # don't bubble up to root


def run_collection_orchestration(
    spreadsheet_id: str,
    downloaded_storage_root: Path,
    wasapi_base_url: str,
    archive_it_credentials: tuple[str, str],
) -> None:
    """
    Runs the current sequential collection orchestration flow.
    Called by: main()
    """
    sheet_context = load_collection_sheet_context(spreadsheet_id)
    collection_jobs = sheet_context.collection_jobs
    worksheet = sheet_context.worksheet
    header_location = sheet_context.header_location
    coordination_mode = get_run_coordination_mode()
    enforce_startup_run_coordination(
        coordination_mode,
        sheet_context.values,
        header_location,
        collection_jobs,
    )
    log.debug('active collections found, ``%s``', collection_jobs)

    timeout = httpx.Timeout(30.0, connect=30.0)
    with httpx.Client(auth=archive_it_credentials, timeout=timeout, follow_redirects=True) as client:
        for collection_job in collection_jobs:
            try:
                process_collection_job(
                    client,
                    collection_job,
                    downloaded_storage_root,
                    wasapi_base_url,
                    worksheet,
                    header_location,
                )
            except WasapiDiscoveryError as exc:
                partial_result = exc.partial_result
                partial_record_count = 0 if partial_result is None else len(partial_result.records)
                log.exception(
                    'Collection %s discovery failed after %s partial records.',
                    collection_job.collection_id,
                    partial_record_count,
                )
                failure_report = build_collection_failure_report(
                    storage_root=downloaded_storage_root,
                    collection_job=collection_job,
                    status_main=STATUS_DISCOVERY_FAILED,
                    status_detail=f'discovery failed after {partial_record_count} partial records',
                    reported_at=datetime.now(UTC).isoformat(),
                )
                try:
                    write_collection_final_report(worksheet, header_location, collection_job, failure_report)
                except Exception:
                    log.exception(
                        'Collection %s final spreadsheet reporting failed after discovery failure.',
                        collection_job.collection_id,
                    )
            except Exception:
                log.exception('Collection %s processing failed.', collection_job.collection_id)
                failure_report = build_collection_failure_report(
                    storage_root=downloaded_storage_root,
                    collection_job=collection_job,
                    status_main=STATUS_SPREADSHEET_UPDATE_FAILED,
                    status_detail='collection processing or reporting failed',
                    reported_at=datetime.now(UTC).isoformat(),
                )
                try:
                    write_collection_final_report(worksheet, header_location, collection_job, failure_report)
                except Exception:
                    log.exception(
                        'Collection %s final spreadsheet reporting failed after processing error.',
                        collection_job.collection_id,
                    )


## manager function -------------------------------------------------
def main() -> None:
    """
    Orchestrates the current sheet, state, and WASAPI discovery flow.
    Called by: __main__
    """
    log.info('\n\nstarting-processing')
    ## get environment variables ------------------------------------
    spreadsheet_id: str | None = os.getenv('GSHEET_SPREADSHEET_ID')
    if spreadsheet_id is None:
        log.error('Missing GSHEET_SPREADSHEET_ID environment variable.')
        return None
    archive_it_credentials = get_archive_it_credentials()
    if archive_it_credentials is None:
        log.error(
            'Missing Archive-It credentials. Set ARCHIVEIT_WASAPI_USERNAME/ARCHIVEIT_WASAPI_PASSWORD or '
            'ARCHIVEIT_USER/ARCHIVEIT_PASS.',
        )
        return None
    downloaded_storage_root = get_downloaded_storage_root()
    wasapi_base_url = os.getenv('ARCHIVEIT_WASAPI_BASE_URL', DEFAULT_WASAPI_BASE_URL)
    log.debug('envars loaded')

    try:
        run_collection_orchestration(spreadsheet_id, downloaded_storage_root, wasapi_base_url, archive_it_credentials)
    except CollectionSheetContractError:
        log.exception('Collection worksheet reporting contract validation failed.')
    except RunCoordinationError:
        log.exception('Startup run coordination preflight refused to begin processing.')
    log.info('processing complete')
    return None


if __name__ == '__main__':
    main()
