"""
Downloads metadata (not WARC files) for a single Archive-It collection using the WASAPI endpoint.

Usage:
    uv run ./tmp_inspect_collection_wasapi.py --collection-id 12345 --output-dir ./output_dir

Note that the created output_dir will have a timestamp appended to the directory-name.
"""

import argparse
import json
import logging
import os
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import dotenv
import httpx

dotenv.load_dotenv()

DEFAULT_WASAPI_BASE_URL = 'https://warcs.archive-it.org/wasapi/v1/webdata'
DEFAULT_PAGE_SIZE = 100
PATH_UNSAFE_CHARACTERS = set('/\\\x00\n\r\t')
IDENTIFIER_FIELD_CANDIDATES = (
    'identifier',
    'item_identifier',
    'archive_identifier',
    'ia_identifier',
    'crawl_id',
    'crawl',
    'file_id',
)
FILENAME_FIELD_CANDIDATES = (
    'filename',
    'name',
    'original_filename',
    'original-name',
    'file_name',
)


@dataclass(frozen=True)
class RequestRecord:
    """
    Represents metadata for one HTTP request.
    """

    page_number: int
    requested_url: str
    requested_params: dict[str, object]
    requested_at_utc: str
    status_code: int | None


@dataclass(frozen=True)
class FetchResult:
    """
    Represents the fetched response pages and request history.
    """

    pages: list[dict[str, object]]
    request_records: list[RequestRecord]


class WasapiFetchError(RuntimeError):
    """
    Represents a fetch failure that may still include partial results.
    """

    def __init__(self, message: str, result: FetchResult):
        super().__init__(message)
        self.result = result


log = logging.getLogger(__name__)


def get_archive_it_credentials() -> tuple[str, str]:
    """
    Returns Archive-It credentials from the environment.
    """
    username = os.getenv('ARCHIVEIT_WASAPI_USERNAME') or os.getenv('ARCHIVEIT_USER')
    password = os.getenv('ARCHIVEIT_WASAPI_PASSWORD') or os.getenv('ARCHIVEIT_PASS')
    if not username or not password:
        raise ValueError(
            'Missing Archive-It credentials. Set ARCHIVEIT_WASAPI_USERNAME/ARCHIVEIT_WASAPI_PASSWORD '
            'or ARCHIVEIT_USER/ARCHIVEIT_PASS.',
        )
    result = (username, password)
    return result


def build_output_paths(output_dir: Path, collection_id: int, requested_at: datetime) -> dict[str, Path]:
    """
    Builds the output paths for a collection capture run.
    """
    timestamp = requested_at.strftime('%Y%m%dT%H%M%SZ')
    collection_directory = output_dir / f'collection_{collection_id}' / timestamp
    pages_directory = collection_directory / 'pages'
    result = {
        'collection_directory': collection_directory,
        'pages_directory': pages_directory,
        'manifest_path': collection_directory / 'request_manifest.json',
        'summary_json_path': collection_directory / 'derived_summary.json',
        'summary_markdown_path': collection_directory / 'derived_summary.md',
    }
    return result


def extract_records_from_page(page_payload: dict[str, object]) -> list[dict[str, object]]:
    """
    Extracts record-like objects from a WASAPI page payload.
    """
    result: list[dict[str, object]] = []
    for key in ('results', 'files', 'items', 'data'):
        candidate = page_payload.get(key)
        if isinstance(candidate, list):
            result = [item for item in candidate if isinstance(item, dict)]
            break
    return result


def get_next_page_number(page_payload: dict[str, object], current_page_number: int) -> int | None:
    """
    Determines the next page number when it can be inferred from the payload.
    """
    result: int | None = None
    next_value = page_payload.get('next')
    if isinstance(next_value, str) and next_value:
        if 'page=' in next_value:
            fragment = next_value.split('page=', 1)[1].split('&', 1)[0]
            if fragment.isdigit():
                result = int(fragment)
        elif next_value.isdigit():
            result = int(next_value)
    elif isinstance(next_value, int):
        result = next_value
    else:
        total_pages = page_payload.get('pages') or page_payload.get('total_pages') or page_payload.get('page_count')
        if isinstance(total_pages, int) and current_page_number < total_pages:
            result = current_page_number + 1
    return result


def fetch_collection_wasapi_pages(
    client: httpx.Client,
    base_url: str,
    collection_id: int,
    page_size: int,
) -> FetchResult:
    """
    Fetches paginated WASAPI JSON for a single collection.
    """
    pages: list[dict[str, object]] = []
    request_records: list[RequestRecord] = []
    page_number = 1
    while True:
        requested_at = datetime.now(UTC)
        params: dict[str, object] = {
            'collection': collection_id,
            'page': page_number,
            'page_size': page_size,
        }
        response: httpx.Response | None = None
        try:
            response = client.get(base_url, params=params)
            request_records.append(
                RequestRecord(
                    page_number=page_number,
                    requested_url=str(response.request.url),
                    requested_params=params,
                    requested_at_utc=requested_at.isoformat(),
                    status_code=response.status_code,
                ),
            )
            response.raise_for_status()
            page_payload = response.json()
            if not isinstance(page_payload, dict):
                raise ValueError('WASAPI response JSON is not an object.')
            pages.append(page_payload)
        except Exception as exc:
            request_url = base_url if response is None else str(response.request.url)
            if response is None:
                request_records.append(
                    RequestRecord(
                        page_number=page_number,
                        requested_url=request_url,
                        requested_params=params,
                        requested_at_utc=requested_at.isoformat(),
                        status_code=None,
                    ),
                )
            partial_result = FetchResult(pages=pages, request_records=request_records)
            raise WasapiFetchError(f'Failed fetching page {page_number}: {exc}', partial_result) from exc

        next_page_number = get_next_page_number(page_payload, page_number)
        page_records = extract_records_from_page(page_payload)
        if next_page_number is None and not page_records:
            break
        if next_page_number is None:
            break
        page_number = next_page_number

    result = FetchResult(pages=pages, request_records=request_records)
    return result


def find_first_string(record: dict[str, object], field_names: tuple[str, ...]) -> str | None:
    """
    Returns the first non-empty string found for the candidate field names.
    """
    result: str | None = None
    for field_name in field_names:
        candidate = record.get(field_name)
        if isinstance(candidate, str) and candidate.strip():
            result = candidate
            break
    return result


def detect_filename_anomalies(filename: str) -> list[str]:
    """
    Detects simple filename/path anomalies for manual review.
    """
    anomalies: list[str] = []
    if any(character in PATH_UNSAFE_CHARACTERS for character in filename):
        anomalies.append('contains_path_unsafe_character')
    if len(filename) > 180:
        anomalies.append('long_filename')
    if filename.strip() != filename:
        anomalies.append('leading_or_trailing_whitespace')
    result = anomalies
    return result


def build_metadata_summary(pages: list[dict[str, object]]) -> dict[str, object]:
    """
    Builds a descriptive summary from saved WASAPI pages.
    """
    records: list[dict[str, object]] = []
    for page_payload in pages:
        records.extend(extract_records_from_page(page_payload))

    filenames: list[str] = []
    identifier_field_names: set[str] = set()
    anomaly_examples: list[dict[str, object]] = []
    record_identifier_count = 0

    for record in records:
        filename = find_first_string(record, FILENAME_FIELD_CANDIDATES)
        if filename is not None:
            filenames.append(filename)
            anomalies = detect_filename_anomalies(filename)
            if anomalies:
                anomaly_examples.append({'filename': filename, 'anomalies': anomalies})

        identifier_found = False
        for field_name in IDENTIFIER_FIELD_CANDIDATES:
            field_value = record.get(field_name)
            if isinstance(field_value, str) and field_value.strip():
                identifier_field_names.add(field_name)
                identifier_found = True
        if identifier_found:
            record_identifier_count += 1

    filename_counter = Counter(filenames)
    duplicate_filenames = [filename for filename, count in filename_counter.items() if count > 1]

    flat_layout_assessment = 'still_unclear'
    if duplicate_filenames:
        flat_layout_assessment = 'obviously_unsafe'
    elif filenames and not anomaly_examples:
        flat_layout_assessment = 'appears_safe_in_sample'

    result = {
        'total_pages_saved': len(pages),
        'total_records_observed': len(records),
        'records_with_filenames': len(filenames),
        'distinct_filenames': len(filename_counter),
        'duplicate_filenames': duplicate_filenames[:25],
        'duplicate_filename_count': len(duplicate_filenames),
        'records_with_identifier_like_fields': record_identifier_count,
        'identifier_field_names_observed': sorted(identifier_field_names),
        'filename_anomaly_examples': anomaly_examples[:25],
        'flat_layout_assessment': flat_layout_assessment,
    }
    return result


def build_capture_manifest(
    collection_id: int,
    base_url: str,
    output_paths: dict[str, Path],
    fetch_result: FetchResult,
    summary: dict[str, object],
    failure_message: str | None,
) -> dict[str, object]:
    """
    Builds a manifest describing the captured output.
    """
    result = {
        'collection_id': collection_id,
        'wasapi_base_url': base_url,
        'pages_directory': str(output_paths['pages_directory'].name),
        'saved_page_files': [f'pages/page_{index:04d}.json' for index, _ in enumerate(fetch_result.pages, start=1)],
        'page_count': len(fetch_result.pages),
        'request_count': len(fetch_result.request_records),
        'request_records': [
            {
                'page_number': record.page_number,
                'requested_url': record.requested_url,
                'requested_params': record.requested_params,
                'requested_at_utc': record.requested_at_utc,
                'status_code': record.status_code,
            }
            for record in fetch_result.request_records
        ],
        'summary_excerpt': {
            'total_records_observed': summary['total_records_observed'],
            'duplicate_filename_count': summary['duplicate_filename_count'],
            'flat_layout_assessment': summary['flat_layout_assessment'],
        },
        'failure_message': failure_message,
    }
    return result


def write_json(path: Path, payload: dict[str, object]) -> None:
    """
    Writes JSON to disk with stable formatting.
    """
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def save_raw_wasapi_pages(pages_directory: Path, pages: list[dict[str, object]]) -> list[Path]:
    """
    Saves raw WASAPI JSON pages to disk.
    """
    saved_paths: list[Path] = []
    pages_directory.mkdir(parents=True, exist_ok=True)
    for index, page_payload in enumerate(pages, start=1):
        page_path = pages_directory / f'page_{index:04d}.json'
        write_json(page_path, page_payload)
        saved_paths.append(page_path)
    result = saved_paths
    return result


def build_summary_markdown(collection_id: int, summary: dict[str, object]) -> str:
    """
    Builds a human-readable markdown summary.
    """
    duplicate_filenames = summary['duplicate_filenames']
    anomaly_examples = summary['filename_anomaly_examples']
    lines = [
        f'# Collection {collection_id} WASAPI summary',
        '',
        f'- total pages saved: {summary["total_pages_saved"]}',
        f'- total records observed: {summary["total_records_observed"]}',
        f'- records with filenames: {summary["records_with_filenames"]}',
        f'- distinct filenames: {summary["distinct_filenames"]}',
        f'- duplicate filename count: {summary["duplicate_filename_count"]}',
        f'- records with identifier-like fields: {summary["records_with_identifier_like_fields"]}',
        f'- identifier field names observed: {", ".join(summary["identifier_field_names_observed"]) or "none"}',
        f'- flat layout assessment: {summary["flat_layout_assessment"]}',
        '',
        '## Duplicate filenames',
        '',
    ]
    if duplicate_filenames:
        lines.extend([f'- {filename}' for filename in duplicate_filenames])
    else:
        lines.append('- none observed in captured sample')
    lines.extend(['', '## Filename anomaly examples', ''])
    if anomaly_examples:
        for example in anomaly_examples:
            lines.append(f'- {example["filename"]}: {", ".join(example["anomalies"])}')
    else:
        lines.append('- none observed in captured sample')
    result = '\n'.join(lines) + '\n'
    return result


def parse_args() -> argparse.Namespace:
    """
    Parses CLI arguments for the investigative script.
    """
    parser = argparse.ArgumentParser(description='Capture Archive-It WASAPI metadata for one collection.')
    parser.add_argument('--collection-id', required=True, type=int, help='Archive-It collection id to inspect')
    parser.add_argument('--output-dir', required=True, help='Directory under which capture output should be created')
    parser.add_argument('--log-level', default=os.getenv('LOG_LEVEL', 'INFO'), help='Logging level')
    parser.add_argument(
        '--page-size',
        type=int,
        default=int(os.getenv('ARCHIVEIT_WASAPI_PAGE_SIZE', str(DEFAULT_PAGE_SIZE))),
        help='Requested WASAPI page size',
    )
    result = parser.parse_args()
    return result


def configure_logging(log_level_name: str) -> None:
    """
    Configures process logging.
    """
    log_level = getattr(logging, log_level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format='[%(asctime)s] %(levelname)s [%(module)s-%(funcName)s()::%(lineno)d] %(message)s',
        datefmt='%d/%b/%Y %H:%M:%S',
    )


def main() -> None:
    """
    Captures raw WASAPI metadata and derived summaries for one collection.
    """
    args = parse_args()
    configure_logging(args.log_level)
    wasapi_base_url = os.getenv('ARCHIVEIT_WASAPI_BASE_URL', DEFAULT_WASAPI_BASE_URL)

    requested_at = datetime.now(UTC)
    output_paths = build_output_paths(Path(args.output_dir), args.collection_id, requested_at)
    output_paths['collection_directory'].mkdir(parents=True, exist_ok=False)
    output_paths['pages_directory'].mkdir(parents=True, exist_ok=False)

    username, password = get_archive_it_credentials()
    timeout = httpx.Timeout(30.0, connect=30.0)
    fetch_result = FetchResult(pages=[], request_records=[])
    failure_message: str | None = None

    with httpx.Client(auth=(username, password), timeout=timeout, follow_redirects=True) as client:
        try:
            fetch_result = fetch_collection_wasapi_pages(
                client=client,
                base_url=wasapi_base_url,
                collection_id=args.collection_id,
                page_size=args.page_size,
            )
        except WasapiFetchError as exc:
            fetch_result = exc.result
            failure_message = str(exc)
            log.exception('WASAPI capture ended with a partial failure.')

    save_raw_wasapi_pages(output_paths['pages_directory'], fetch_result.pages)
    summary = build_metadata_summary(fetch_result.pages)
    manifest = build_capture_manifest(
        collection_id=args.collection_id,
        base_url=wasapi_base_url,
        output_paths=output_paths,
        fetch_result=fetch_result,
        summary=summary,
        failure_message=failure_message,
    )
    write_json(output_paths['manifest_path'], manifest)
    write_json(output_paths['summary_json_path'], summary)
    output_paths['summary_markdown_path'].write_text(
        build_summary_markdown(args.collection_id, summary),
        encoding='utf-8',
    )

    log.info('Capture directory: %s', output_paths['collection_directory'])
    log.info('Pages saved: %s', len(fetch_result.pages))
    log.info('Records observed: %s', summary['total_records_observed'])
    if failure_message is not None:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
