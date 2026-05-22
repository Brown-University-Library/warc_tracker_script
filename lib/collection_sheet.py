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
    'status_last_fetch',
    'status_last_fetch_file_count',
    'last_download_timestamp',
    'total_col_warc_count',
    'total_downloaded_collection_size',
    'server_file_path_collection_level',
    'seed_count',
)

HEADER_ALIASES: dict[str, set[str]] = {
    'collection_id': {'collection id'},
    'repository': {'repository'},
    'collection_url': {'collection url'},
    'collection_name': {'collection name'},
    'seed_count': {'seed count'},
    'active_inactive': {'active/inactive', 'active / inactive'},
    'status_last_fetch': {'status-last-fetch', 'processing_status_main', 'status-main'},
    'status_last_fetch_file_count': {
        'status-last-fetch-file-count',
        'processing_status_detail',
        'status-detail',
    },
    'last_download_timestamp': {
        'last-download-timestamp',
        'summary_status_last_wasapi_check',
        'sum--last-check-timestamp',
    },
    'total_col_warc_count': {
        'total-col-warc-count',
        'summary_status_downloaded_warcs_count',
        'sum--downloaded-warcs-count',
    },
    'total_downloaded_collection_size': {
        'total-downloaded-collection-size',
        'summary_status_downloaded_warcs_size',
        'sum--downloaded-warcs-size',
    },
    'server_file_path_collection_level': {
        'server-file-path-collectionlevel',
        'summary_status_server_path',
        'sum--downloaded-warcs-server-path',
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
    values: list[list[str]]
    collection_jobs: list[CollectionJob]


class CollectionSheetContractError(ValueError):
    """
    Indicates that the collection worksheet does not satisfy the required column contract.
    """


@dataclass(frozen=True, init=False)
class CollectionProcessingStatusUpdate:
    """
    Represents a collection-level processing status update payload.
    """

    status_last_fetch: str
    status_last_fetch_file_count: str

    def __init__(
        self,
        status_last_fetch: str | None = None,
        status_last_fetch_file_count: str | None = None,
        processing_status_main: str | None = None,
        processing_status_detail: str | None = None,
    ) -> None:
        """
        Initializes a status update from canonical or legacy field names.
        Called by: orchestration.build_collection_status_update()
        """
        resolved_status = status_last_fetch if status_last_fetch is not None else processing_status_main
        resolved_count = (
            status_last_fetch_file_count
            if status_last_fetch_file_count is not None
            else processing_status_detail
        )
        object.__setattr__(self, 'status_last_fetch', resolved_status or '')
        object.__setattr__(self, 'status_last_fetch_file_count', resolved_count or '')

    @property
    def processing_status_main(self) -> str:
        """
        Returns the legacy status-main field value.
        Called by: no_production_caller()
        """
        result = self.status_last_fetch
        return result

    @property
    def processing_status_detail(self) -> str:
        """
        Returns the legacy status-detail field value.
        Called by: no_production_caller()
        """
        result = self.status_last_fetch_file_count
        return result


@dataclass(frozen=True, init=False)
class CollectionSummaryUpdate:
    """
    Represents summary-field values written after collection processing completes.
    """

    last_download_timestamp: str
    total_col_warc_count: str
    total_downloaded_collection_size: str
    server_file_path_collection_level: str
    seed_count: str

    def __init__(
        self,
        last_download_timestamp: str | None = None,
        total_col_warc_count: str | None = None,
        total_downloaded_collection_size: str | None = None,
        server_file_path_collection_level: str | None = None,
        seed_count: str | None = None,
        summary_status_last_wasapi_check: str | None = None,
        summary_status_downloaded_warcs_count: str | None = None,
        summary_status_downloaded_warcs_size: str | None = None,
        summary_status_server_path: str | None = None,
    ) -> None:
        """
        Initializes a summary update from canonical or legacy field names.
        Called by: orchestration.build_collection_summary_update()
        """
        resolved_timestamp = (
            last_download_timestamp
            if last_download_timestamp is not None
            else summary_status_last_wasapi_check
        )
        resolved_warc_count = (
            total_col_warc_count
            if total_col_warc_count is not None
            else summary_status_downloaded_warcs_count
        )
        resolved_size = (
            total_downloaded_collection_size
            if total_downloaded_collection_size is not None
            else summary_status_downloaded_warcs_size
        )
        resolved_server_path = (
            server_file_path_collection_level
            if server_file_path_collection_level is not None
            else summary_status_server_path
        )
        object.__setattr__(self, 'last_download_timestamp', resolved_timestamp or '')
        object.__setattr__(self, 'total_col_warc_count', resolved_warc_count or '')
        object.__setattr__(self, 'total_downloaded_collection_size', resolved_size or '')
        object.__setattr__(self, 'server_file_path_collection_level', resolved_server_path or '')
        object.__setattr__(self, 'seed_count', seed_count or '')

    @property
    def summary_status_last_wasapi_check(self) -> str:
        """
        Returns the legacy last-check field value.
        Called by: no_production_caller()
        """
        result = self.last_download_timestamp
        return result

    @property
    def summary_status_downloaded_warcs_count(self) -> str:
        """
        Returns the legacy downloaded-WARC-count field value.
        Called by: no_production_caller()
        """
        result = self.total_col_warc_count
        return result

    @property
    def summary_status_downloaded_warcs_size(self) -> str:
        """
        Returns the legacy downloaded-WARC-size field value.
        Called by: no_production_caller()
        """
        result = self.total_downloaded_collection_size
        return result

    @property
    def summary_status_server_path(self) -> str:
        """
        Returns the legacy server-path field value.
        Called by: no_production_caller()
        """
        result = self.server_file_path_collection_level
        return result


def load_gsheet_credentials() -> dict[str, str]:
    """
    Loads service-account credentials from the environment.
    Called by: get_gspread_client()
    """
    credentials_json = os.getenv('GSHEET_CREDENTIALS_JSON')
    if not credentials_json:
        raise ValueError('Missing GSHEET_CREDENTIALS_JSON environment variable.')

    result = json.loads(credentials_json)
    return result


def get_gspread_client(*, read_only: bool = True) -> gspread.Client:
    """
    Returns a gspread client authorized for read-only or read-write access.
    Called by: get_collection_worksheet()
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
    Called by: fetch_collection_jobs()
    """
    client = get_gspread_client(read_only=read_only)
    spreadsheet = client.open_by_key(spreadsheet_id)
    result = spreadsheet.worksheet(COLLECTION_SHEET_NAME)
    return result


def normalize_header_value(value: str) -> str:
    """
    Normalizes header values for matching against known aliases.
    Called by: locate_header_row()
    """
    collapsed = ' '.join(value.strip().split())
    normalized = collapsed.replace(' / ', '/').replace(' /', '/').replace('/ ', '/')
    result = normalized.casefold()
    return result


def locate_header_row(values: list[list[str]]) -> HeaderLocation | None:
    """
    Locates the header row and returns its column map.
    Called by: parse_collection_jobs()
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
    Called by: parse_collection_jobs()
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
    Called by: fetch_collection_jobs()
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
    Called by: parse_collection_jobs()
    """
    result: str | None = None
    if column_index is not None and column_index < len(row):
        cell_value = row[column_index].strip()
        if cell_value:
            result = cell_value
    return result


# def fetch_collection_jobs(spreadsheet_id: str) -> list[CollectionJob]:
#     """
#     Fetches active collection jobs from the collection-level worksheet.
#     Called by: no_production_caller()
#     """
#     worksheet = get_collection_worksheet(spreadsheet_id)
#     values = worksheet.get_all_values()
#     result = parse_collection_jobs(values)
#     return result


def validate_required_reporting_fields(header_location: HeaderLocation) -> None:
    """
    Validates that the required reporting columns exist in the worksheet header.
    Called by: load_collection_sheet_context()
    """
    missing_fields = [field_name for field_name in REQUIRED_REPORTING_FIELDS if field_name not in header_location.column_map]
    if missing_fields:
        missing_field_display = ', '.join(missing_fields)
        raise CollectionSheetContractError(f'Missing required collection reporting columns: {missing_field_display}')


def load_collection_sheet_context(spreadsheet_id: str) -> CollectionSheetContext:
    """
    Loads the collection worksheet, validates the reporting contract, and parses active collection jobs.
    Called by: run_collection_orchestration(), validate_collection_sheet_connection()
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
        values=values,
        collection_jobs=collection_jobs,
    )
    return result


def build_spreadsheet_editability_probe_update(
    values: list[list[str]],
    header_location: HeaderLocation,
) -> list[dict[str, object]]:
    """
    Builds a same-value worksheet update that can prove spreadsheet editability.
    Called by: validate_collection_sheet_connection()
    """
    field_name = 'status_last_fetch'
    row_index = header_location.header_row_index
    column_index = get_column_index(header_location, field_name)
    cell_value = values[row_index][column_index]
    result = [
        {
            'range': gspread.utils.rowcol_to_a1(row_index + 1, column_index + 1),
            'values': [[cell_value]],
        }
    ]
    return result


def get_column_index(header_location: HeaderLocation, field_name: str) -> int:
    """
    Returns a column index for canonical or legacy field names.
    Called by: build_collection_status_cell_updates()
    """
    legacy_field_names = {
        'status_last_fetch': ('processing_status_main',),
        'status_last_fetch_file_count': ('processing_status_detail',),
        'last_download_timestamp': ('summary_status_last_wasapi_check',),
        'total_col_warc_count': ('summary_status_downloaded_warcs_count',),
        'total_downloaded_collection_size': ('summary_status_downloaded_warcs_size',),
        'server_file_path_collection_level': ('summary_status_server_path',),
    }
    candidate_field_names = (field_name, *legacy_field_names.get(field_name, ()))
    result: int | None = None
    for candidate_field_name in candidate_field_names:
        if candidate_field_name in header_location.column_map:
            result = header_location.column_map[candidate_field_name]
            break
    if result is None:
        raise CollectionSheetContractError(f'Missing required collection reporting column: {field_name}')
    return result


def validate_collection_sheet_connection(spreadsheet_id: str) -> CollectionSheetContext:
    """
    Validates that the collection worksheet can be opened, parsed, and edited.
    Called by: validate_spreadsheet_connection.run_validation()
    """
    result = load_collection_sheet_context(spreadsheet_id)
    editability_probe_update = build_spreadsheet_editability_probe_update(result.values, result.header_location)
    result.worksheet.batch_update(editability_probe_update)
    return result


def build_collection_status_cell_updates(
    header_location: HeaderLocation,
    row_number: int,
    status_update: CollectionProcessingStatusUpdate,
) -> list[dict[str, str]]:
    """
    Builds worksheet cell updates for collection status fields.
    Called by: update_collection_processing_status()
    """
    result = [
        {
            'range': gspread.utils.rowcol_to_a1(row_number, get_column_index(header_location, 'status_last_fetch') + 1),
            'values': [[status_update.status_last_fetch]],
        },
        {
            'range': gspread.utils.rowcol_to_a1(
                row_number,
                get_column_index(header_location, 'status_last_fetch_file_count') + 1,
            ),
            'values': [[status_update.status_last_fetch_file_count]],
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
    Called by: update_collection_final_reporting()
    """
    summary_values = {
        'last_download_timestamp': summary_update.last_download_timestamp,
        'total_col_warc_count': summary_update.total_col_warc_count,
        'total_downloaded_collection_size': summary_update.total_downloaded_collection_size,
        'server_file_path_collection_level': summary_update.server_file_path_collection_level,
        'seed_count': summary_update.seed_count,
    }
    result: list[dict[str, str]] = []
    for field_name, field_value in summary_values.items():
        result.append(
            {
                'range': gspread.utils.rowcol_to_a1(row_number, get_column_index(header_location, field_name) + 1),
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
    Called by: write_collection_status_update()
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
    Called by: write_collection_final_report()
    """
    cell_updates = build_collection_status_cell_updates(header_location, row_number, status_update)
    cell_updates.extend(build_collection_summary_cell_updates(header_location, row_number, summary_update))
    worksheet.batch_update(cell_updates)
