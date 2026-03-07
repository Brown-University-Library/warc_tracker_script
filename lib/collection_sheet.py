import json
import logging
import os
from dataclasses import dataclass

import dotenv
import gspread
from google.oauth2.service_account import Credentials

dotenv.load_dotenv()

log = logging.getLogger(__name__)

COLLECTION_SHEET_NAME = 'At Collection Level'
REQUIRED_HEADER_FIELDS = ('collection_id', 'active_inactive')
REQUIRED_REPORTING_FIELDS = (
    'processing_status_main',
    'processing_status_detail',
    'summary_status_last_wasapi_check',
    'summary_status_downloaded_warcs_count',
    'summary_status_downloaded_warcs_size',
    'summary_status_server_path',
)

HEADER_ALIASES: dict[str, set[str]] = {
    'collection_id': {'collection id'},
    'repository': {'repository'},
    'collection_url': {'collection url'},
    'collection_name': {'collection name'},
    'active_inactive': {'active/inactive', 'active / inactive'},
    'processing_status_main': {'processing_status_main', 'status-main'},
    'processing_status_detail': {'processing_status_detail', 'status-detail'},
    'summary_status_last_wasapi_check': {
        'summary_status_last_wasapi_check',
        'sum--last-check-timestamp',
    },
    'summary_status_downloaded_warcs_count': {
        'summary_status_downloaded_warcs_count',
        'sum--downloaded-warcs-count',
    },
    'summary_status_downloaded_warcs_size': {
        'summary_status_downloaded_warcs_size',
        'sum--downloaded-warcs-size',
    },
    'summary_status_server_path': {
        'summary_status_server_path',
        'sum--dowlnloaded-warcs-server-path',
    },
}


@dataclass(frozen=True)
class HeaderLocation:
    """
    Represents the header row index and column map for a sheet.
    """

    header_row_index: int
    column_map: dict[str, int]


@dataclass(frozen=True)
class CollectionJob:
    """
    Represents an active collection entry with row metadata.
    """

    collection_id: int
    repository: str | None
    collection_url: str | None
    collection_name: str | None
    row_number: int


@dataclass(frozen=True)
class CollectionSheetContext:
    """
    Represents the worksheet plus parsed header metadata for collection reporting.
    """

    worksheet: gspread.Worksheet
    header_location: HeaderLocation
    collection_jobs: list[CollectionJob]


class CollectionSheetContractError(ValueError):
    """
    Indicates that the collection worksheet does not satisfy the required column contract.
    """


@dataclass(frozen=True)
class CollectionProcessingStatusUpdate:
    """
    Represents a collection-level processing status update payload.
    """

    processing_status_main: str
    processing_status_detail: str


@dataclass(frozen=True)
class CollectionSummaryUpdate:
    """
    Represents summary-field values written after collection processing completes.
    """

    summary_status_last_wasapi_check: str
    summary_status_downloaded_warcs_count: str
    summary_status_downloaded_warcs_size: str
    summary_status_server_path: str


def load_gsheet_credentials() -> dict[str, str]:
    """
    Loads service-account credentials from the environment.
    """
    credentials_json = os.getenv('GSHEET_CREDENTIALS_JSON')
    if not credentials_json:
        raise ValueError('Missing GSHEET_CREDENTIALS_JSON environment variable.')

    result = json.loads(credentials_json)
    return result


def get_gspread_client(*, read_only: bool = True) -> gspread.Client:
    """
    Returns a gspread client authorized for read-only or read-write access.
    """
    credentials_data = load_gsheet_credentials()
    scopes = ['https://www.googleapis.com/auth/spreadsheets.readonly']
    if not read_only:
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
    credentials = Credentials.from_service_account_info(credentials_data, scopes=scopes)
    result = gspread.authorize(credentials)
    return result


def get_collection_worksheet(spreadsheet_id: str, *, read_only: bool = True) -> gspread.Worksheet:
    """
    Returns the collection-level worksheet from the spreadsheet.
    """
    client = get_gspread_client(read_only=read_only)
    spreadsheet = client.open_by_key(spreadsheet_id)
    result = spreadsheet.worksheet(COLLECTION_SHEET_NAME)
    return result


def normalize_header_value(value: str) -> str:
    """
    Normalizes header values for matching against known aliases.
    """
    collapsed = ' '.join(value.strip().split())
    normalized = collapsed.replace(' / ', '/').replace(' /', '/').replace('/ ', '/')
    result = normalized.casefold()
    return result


def locate_header_row(values: list[list[str]]) -> HeaderLocation | None:
    """
    Locates the header row and returns its column map.
    """
    result: HeaderLocation | None = None
    alias_to_field: dict[str, str] = {}
    for field, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            alias_to_field[alias.casefold()] = field

    for row_index, row in enumerate(values):
        column_map: dict[str, int] = {}
        for column_index, cell_value in enumerate(row):
            normalized = normalize_header_value(cell_value)
            field_name = alias_to_field.get(normalized)
            if field_name and field_name not in column_map:
                column_map[field_name] = column_index

        if all(field in column_map for field in REQUIRED_HEADER_FIELDS):
            result = HeaderLocation(header_row_index=row_index, column_map=column_map)
            break

    return result


def parse_collection_id(value: str | None) -> int | None:
    """
    Parses a collection id value into an integer if possible.
    """
    result: int | None = None
    if value is not None:
        cleaned = value.strip()
        if cleaned:
            try:
                result = int(cleaned)
            except ValueError:
                try:
                    float_value = float(cleaned)
                except ValueError:
                    result = None
                else:
                    if float_value.is_integer():
                        result = int(float_value)

    return result


def parse_collection_jobs(values: list[list[str]]) -> list[CollectionJob]:
    """
    Parses collection jobs from a sheet value grid.
    """
    header_location = locate_header_row(values)
    result: list[CollectionJob] = []
    if header_location is None:
        log.error('Unable to locate collection sheet header row.')
    else:
        data_start_index = header_location.header_row_index + 1
        for row_offset, row in enumerate(values[data_start_index:]):
            row_number = data_start_index + row_offset + 1
            collection_id_cell = get_row_cell(row, header_location.column_map.get('collection_id'))
            collection_id = parse_collection_id(collection_id_cell)
            if collection_id is None:
                continue

            active_value = get_row_cell(row, header_location.column_map.get('active_inactive'))
            active_flag = (active_value or '').strip()
            if active_flag != 'Active':
                if active_flag:
                    log.warning('Skipping collection row %s with unexpected active flag: %s', row_number, active_flag)
                continue

            repository = get_row_cell(row, header_location.column_map.get('repository'))
            collection_url = get_row_cell(row, header_location.column_map.get('collection_url'))
            collection_name = get_row_cell(row, header_location.column_map.get('collection_name'))

            result.append(
                CollectionJob(
                    collection_id=collection_id,
                    repository=repository,
                    collection_url=collection_url,
                    collection_name=collection_name,
                    row_number=row_number,
                ),
            )

    return result


def get_row_cell(row: list[str], column_index: int | None) -> str | None:
    """
    Returns the cell value for a row at the given column index.
    """
    result: str | None = None
    if column_index is not None and column_index < len(row):
        cell_value = row[column_index].strip()
        if cell_value:
            result = cell_value
    return result


def fetch_collection_jobs(spreadsheet_id: str) -> list[CollectionJob]:
    """
    Fetches active collection jobs from the collection-level worksheet.
    """
    worksheet = get_collection_worksheet(spreadsheet_id)
    values = worksheet.get_all_values()
    result = parse_collection_jobs(values)
    return result


def validate_required_reporting_fields(header_location: HeaderLocation) -> None:
    """
    Validates that the required reporting columns exist in the worksheet header.
    """
    missing_fields = [field_name for field_name in REQUIRED_REPORTING_FIELDS if field_name not in header_location.column_map]
    if missing_fields:
        missing_field_display = ', '.join(missing_fields)
        raise CollectionSheetContractError(f'Missing required collection reporting columns: {missing_field_display}')


def load_collection_sheet_context(spreadsheet_id: str) -> CollectionSheetContext:
    """
    Loads the collection worksheet, validates the reporting contract, and parses active collection jobs.
    """
    worksheet = get_collection_worksheet(spreadsheet_id, read_only=False)
    values = worksheet.get_all_values()
    header_location = locate_header_row(values)
    if header_location is None:
        raise CollectionSheetContractError('Unable to locate collection sheet header row.')
    validate_required_reporting_fields(header_location)
    collection_jobs = parse_collection_jobs(values)
    result = CollectionSheetContext(
        worksheet=worksheet,
        header_location=header_location,
        collection_jobs=collection_jobs,
    )
    return result


def build_collection_status_cell_updates(
    header_location: HeaderLocation,
    row_number: int,
    status_update: CollectionProcessingStatusUpdate,
) -> list[dict[str, str]]:
    """
    Builds worksheet cell updates for collection status fields.
    """
    result = [
        {
            'range': gspread.utils.rowcol_to_a1(row_number, header_location.column_map['processing_status_main'] + 1),
            'values': [[status_update.processing_status_main]],
        },
        {
            'range': gspread.utils.rowcol_to_a1(row_number, header_location.column_map['processing_status_detail'] + 1),
            'values': [[status_update.processing_status_detail]],
        },
    ]
    return result


def build_collection_summary_cell_updates(
    header_location: HeaderLocation,
    row_number: int,
    summary_update: CollectionSummaryUpdate,
) -> list[dict[str, str]]:
    """
    Builds worksheet cell updates for collection summary fields.
    """
    summary_values = {
        'summary_status_last_wasapi_check': summary_update.summary_status_last_wasapi_check,
        'summary_status_downloaded_warcs_count': summary_update.summary_status_downloaded_warcs_count,
        'summary_status_downloaded_warcs_size': summary_update.summary_status_downloaded_warcs_size,
        'summary_status_server_path': summary_update.summary_status_server_path,
    }
    result: list[dict[str, str]] = []
    for field_name, field_value in summary_values.items():
        result.append(
            {
                'range': gspread.utils.rowcol_to_a1(row_number, header_location.column_map[field_name] + 1),
                'values': [[field_value]],
            }
        )
    return result


def update_collection_processing_status(
    worksheet: gspread.Worksheet,
    header_location: HeaderLocation,
    row_number: int,
    status_update: CollectionProcessingStatusUpdate,
) -> None:
    """
    Updates the collection row with the current processing status fields.
    """
    cell_updates = build_collection_status_cell_updates(header_location, row_number, status_update)
    worksheet.batch_update(cell_updates)


def update_collection_final_reporting(
    worksheet: gspread.Worksheet,
    header_location: HeaderLocation,
    row_number: int,
    status_update: CollectionProcessingStatusUpdate,
    summary_update: CollectionSummaryUpdate,
) -> None:
    """
    Updates the collection row with final status and summary fields.
    """
    cell_updates = build_collection_status_cell_updates(header_location, row_number, status_update)
    cell_updates.extend(build_collection_summary_cell_updates(header_location, row_number, summary_update))
    worksheet.batch_update(cell_updates)
