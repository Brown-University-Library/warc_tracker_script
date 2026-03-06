import logging
import os
from pathlib import Path

import dotenv

from lib.orchestration import get_archive_it_credentials, get_downloaded_storage_root, run_collection_orchestration
from lib.wasapi_discovery import DEFAULT_WASAPI_BASE_URL

dotenv.load_dotenv()

LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE_PATH: Path = Path(__file__).resolve().parent / 'logs' / 'warc_tracker_script.log'

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


## manager function -------------------------------------------------
def main() -> None:
    """
    Orchestrates the current sheet, state, and WASAPI discovery flow.
    """
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

    run_collection_orchestration(spreadsheet_id, downloaded_storage_root, wasapi_base_url, archive_it_credentials)
    return None


if __name__ == '__main__':
    main()
