import json
import os

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()

GSHEET_CREDENTIALS: dict = json.loads(os.environ['GSHEET_CREDENTIALS_JSON'])
GSHEET_ID: str = os.environ['GSHEET_SPREADSHEET_ID']
LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')


def get_gspread_client() -> gspread.Client:
    """
    Returns a gspread client.
    """
    limited_scopes: list[str] = ['https://www.googleapis.com/auth/spreadsheets']
    credentials: Credentials = Credentials.from_service_account_info(GSHEET_CREDENTIALS, scopes=limited_scopes)
    client: gspread.Client = gspread.authorize(credentials)
    return client
