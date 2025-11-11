import argparse
import json
import logging
import os
import random
from collections.abc import Callable

import dotenv
import gspread
from google.oauth2.service_account import Credentials

import helpers

dotenv.load_dotenv()

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
    Demonstrates how to read from a gsheet via gspread.
    Called by manage_gsheet_writer().
    """
    limited_scopes: list[str] = ['https://www.googleapis.com/auth/spreadsheets.readonly']  # read-only access
    credentials: Credentials = Credentials.from_service_account_info(GSHEET_CREDENTIALS, scopes=limited_scopes)
    client: gspread.Client = gspread.authorize(credentials)
    spsheet: gspread.Spreadsheet = client.open_by_key(GSHEET_ID)
    values_list = spsheet.sheet1.row_values(1)  # sheet1 is the worksheet; row_values(1) is the first row
    log.info(f'values_list: ``{values_list}``')
    return None


def tweak_worksheet() -> None:
    """
    Demonstrates how to update the worksheet-title via gspread.
    Called by manage_gsheet_writer().
    """
    client: gspread.Client = helpers.get_gspread_client()
    spsheet: gspread.Spreadsheet = client.open_by_key(GSHEET_ID)
    sheets = spsheet.worksheets()
    log.info(f'sheets initially: ``{sheets}``')
    # target_sheet: gspread.Worksheet = spsheet.worksheet('Sheet1')  # by name
    target_sheet: gspread.Worksheet = sheets[0]  # by index
    new_title: str = f'new_title_{random.randint(0, 1000):04d}'
    target_sheet.update_title(new_title)
    log.info(f'sheets now: ``{sheets}``')
    return None


def run_simple_write() -> None:
    """
    Demonstrates how to write to a gsheet via gspread.
    Called by manage_gsheet_writer().
    """
    ## get client and spreadsheet -----------------------------------
    client: gspread.Client = helpers.get_gspread_client()
    spsheet: gspread.Spreadsheet = client.open_by_key(GSHEET_ID)
    sheets = spsheet.worksheets()
    ## get target worksheet -----------------------------------------
    target_sheet: gspread.Worksheet = sheets[0]  # by index
    log.info(f'target_sheet: ``{target_sheet}``')
    ## update worksheet value ---------------------------------------
    new_value: str = f'new_value_{random.randint(0, 1000):04d}'
    target_sheet.update_acell('B1', new_value)
    values_list = target_sheet.row_values(1)
    log.info(f'values_list after update: ``{values_list}``')
    return None


def run_find() -> None:
    """
    Demonstrates how to find a value in a gsheet via gspread.
    Called by manage_gsheet_writer().
    """
    client: gspread.Client = helpers.get_gspread_client()
    spsheet: gspread.Spreadsheet = client.open_by_key(GSHEET_ID)
    sheets = spsheet.worksheets()
    target_sheet: gspread.Worksheet = sheets[0]  # by index
    cell: gspread.Cell = target_sheet.find('secret-data-here')
    log.info(f'cell: ``{cell}``')
    log.info(f'cell.row: ``{cell.row}``')
    log.info(f'cell.col: ``{cell.col}``')
    return None


## Allowed actions and function map for CLI ----------------------------
ALLOWED_ACTIONS: list[str] = [
    'run_simple_read',
    'tweak_worksheet',
    'run_simple_write',
    'run_find',
]

FUNCTION_MAP: dict[str, Callable[[], None]] = {
    'run_simple_read': run_simple_read,
    'tweak_worksheet': tweak_worksheet,
    'run_simple_write': run_simple_write,
    'run_find': run_find,
}


# def manage_gsheet_writer() -> None:
#     """
#     Demonstrates how to use the Google Sheets API to read-from and write-to a Google Sheet.
#     """
#     ## confirm we're reading settings -------------------------------
#     log.info(f'project_id, ``{GSHEET_CREDENTIALS["project_id"]}``')
#     log.info(f'service-account-email, ``{GSHEET_CREDENTIALS["client_email"]}``')

#     run_simple_read()
#     tweak_worksheet()
#     run_simple_write()
#     run_find()
#     return None


def main() -> None:
    """
    Parses CLI argument and runs the named action if allowed; otherwise logs an invalid message.
    """
    parser = argparse.ArgumentParser(description='Interact with a Google Sheet via named actions.')
    parser.add_argument(
        'action',
        nargs='?',
        help='One of: ' + ', '.join(ALLOWED_ACTIONS),
    )
    args = parser.parse_args()

    action: str | None = args.action
    if action and action in ALLOWED_ACTIONS:
        log.info(f'running action: `{action}`')
        FUNCTION_MAP[action]()
        return None

    log.error('Invalid or missing action. Provide one of: ' + ', '.join(ALLOWED_ACTIONS))
    return None


if __name__ == '__main__':
    main()
