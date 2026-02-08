import logging
import os

import dotenv

from lib.collection_sheet import fetch_collection_jobs

dotenv.load_dotenv()

LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')


## setup logging
log_level = getattr(logging, LOG_LEVEL)  # maps the string name to the corresponding logging level constant
logging.basicConfig(
    level=log_level,
    format='[%(asctime)s] %(levelname)s [%(module)s-%(funcName)s()::%(lineno)d] %(message)s',
    datefmt='%d/%b/%Y %H:%M:%S',
)
log = logging.getLogger(__name__)


## manager function -------------------------------------------------
def main() -> None:
    """
    Parses CLI argument and runs the named action if allowed; otherwise logs an invalid message.
    """
    spreadsheet_id: str | None = os.getenv('GSHEET_SPREADSHEET_ID')
    if spreadsheet_id is None:
        log.error('Missing GSHEET_SPREADSHEET_ID environment variable.')
        return None

    collection_jobs = fetch_collection_jobs(spreadsheet_id)
    log.info('Active collections found: %s', len(collection_jobs))
    return None


if __name__ == '__main__':
    main()
