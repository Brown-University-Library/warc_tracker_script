import json
import logging
import os

import dotenv
import gspread
from google.oauth2.service_account import Credentials

dotenv.load_dotenv()


## settings ---------------------------------------------------------
GSHEET_CREDENTIALS: dict = json.loads(os.environ['GSHEET_CREDENTIALS_JSON'])
GSHEET_ID: str = os.environ['GSHEET_SPREADSHEET_ID']
LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')


## setup logging
log_level = getattr(logging, LOG_LEVEL)  # maps the string name to the corresponding logging level constant
logging.basicConfig(
    level=log_level,
    format='[%(asctime)s] %(levelname)s [%(module)s-%(funcName)s()::%(lineno)d] %(message)s',
    datefmt='%d/%b/%Y %H:%M:%S',
)
log = logging.getLogger(__name__)


def run_simple_read() -> None:
    """
    Demonstrates how to use the Google Sheets API to read-from a Google Sheet.
    Called by manage_gsheet_writer().
    """
    limited_scopes = ['https://www.googleapis.com/auth/spreadsheets.readonly']
    credentials = Credentials.from_service_account_info(GSHEET_CREDENTIALS, scopes=limited_scopes)
    client = gspread.authorize(credentials)
    sheet = client.open_by_key(GSHEET_ID)
    values_list = sheet.sheet1.row_values(1)

    log.info(f'values_list: ``{values_list}``')
    return None


# def run_simple_write() -> None:
#     """
#     Demonstrates how to use the Google Sheets API to write-to a Google Sheet.
#     """
#     return None


def manage_gsheet_writer() -> None:
    """
    Demonstrates how to use the Google Sheets API to read-from and write-to a Google Sheet.
    """
    # args: Namespace = handle_args()
    # if args.collection_id:
    #     log.debug(f'Processing single collection: {args.collection_id}')
    #     check_collection(args.collection_id)
    # elif args.collection_ids:
    #     log.debug(f'args.collection_ids in manage_tracker_check(): ``{args.collection_ids}``')
    #     log.debug(f'Processing multiple collections: {", ".join(args.collection_ids)}')
    #     for cid in args.collection_ids:
    #         check_collection(cid)

    ## confirm we're reading settings -------------------------------
    log.info(f'project_id, ``{GSHEET_CREDENTIALS["project_id"]}``')
    log.info(f'service-account-email, ``{GSHEET_CREDENTIALS["client_email"]}``')

    ## simple-read --------------------------------------------------
    run_simple_read()

    return None


if __name__ == '__main__':
    manage_gsheet_writer()
