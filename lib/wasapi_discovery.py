import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx

DEFAULT_WASAPI_BASE_URL = 'https://warcs.archive-it.org/wasapi/v1/webdata'
DEFAULT_OVERLAP_DAYS = 30
DEFAULT_PAGE_SIZE = 100
RECORD_LIST_FIELD_CANDIDATES = ('results', 'files', 'items', 'data')

log = logging.getLogger(__name__)


class WasapiDiscoveryError(RuntimeError):
    """
    Represents a discovery failure that may still include partial results.
    """

    def __init__(self, message: str, partial_result: 'DiscoveryResult | None' = None):
        super().__init__(message)
        self.partial_result = partial_result


@dataclass(frozen=True)
class DiscoveryRequestRecord:
    """
    Represents request metadata for one WASAPI page fetch.
    """

    page_number: int
    requested_url: str
    requested_params: dict[str, object]
    requested_at_utc: str
    status_code: int | None


@dataclass(frozen=True)
class DiscoveryResult:
    """
    Represents the result of enumerating WASAPI records for one collection.
    """

    collection_id: int
    after_datetime: datetime
    records: list[dict[str, object]]
    request_records: list[DiscoveryRequestRecord]
    completed_successfully: bool
    max_observed_store_time: str | None


def parse_wasapi_datetime(value: str) -> datetime:
    """
    Parses a WASAPI datetime string into an aware UTC datetime.
    """
    normalized = value.strip()
    if normalized.endswith('Z'):
        normalized = normalized[:-1] + '+00:00'
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError(f'WASAPI datetime must include timezone information: {value}')
    result = parsed.astimezone(UTC)
    return result


def compute_store_time_after_datetime(
    checkpoint_store_time_max: str | None,
    now: datetime,
    overlap_days: int = DEFAULT_OVERLAP_DAYS,
) -> datetime:
    """
    Computes the store-time-after boundary using the overlap window.
    """
    reference_datetime = now.astimezone(UTC)
    if checkpoint_store_time_max is not None:
        reference_datetime = parse_wasapi_datetime(checkpoint_store_time_max)
    result = reference_datetime - timedelta(days=overlap_days)
    return result


def format_wasapi_datetime(value: datetime) -> str:
    """
    Formats an aware datetime in the UTC form expected by WASAPI query params.
    """
    utc_value = value.astimezone(UTC)
    result = utc_value.strftime('%Y-%m-%dT%H:%M:%SZ')
    return result


def extract_discovery_records(page_payload: dict[str, object]) -> list[dict[str, object]]:
    """
    Extracts record payloads from one WASAPI page.
    """
    records: list[dict[str, object]] | None = None
    for field_name in RECORD_LIST_FIELD_CANDIDATES:
        candidate = page_payload.get(field_name)
        if candidate is not None:
            if not isinstance(candidate, list):
                raise WasapiDiscoveryError(f'WASAPI page field `{field_name}` must be a JSON array.')
            if not all(isinstance(item, dict) for item in candidate):
                raise WasapiDiscoveryError(f'WASAPI page field `{field_name}` must contain only JSON objects.')
            records = list(candidate)
            break
    if records is None:
        raise WasapiDiscoveryError('WASAPI page payload is missing a record list field.')
    result = records
    return result


def extract_record_store_time(record: dict[str, object]) -> str | None:
    """
    Extracts a usable store-time string from one record when present.
    """
    result: str | None = None
    candidate = record.get('store-time')
    if isinstance(candidate, str):
        cleaned = candidate.strip()
        if cleaned:
            result = cleaned
    return result


def compute_max_store_time(records: list[dict[str, object]]) -> str | None:
    """
    Computes the maximum usable store-time across discovered records.
    """
    max_datetime: datetime | None = None
    max_store_time: str | None = None
    for record in records:
        store_time = extract_record_store_time(record)
        if store_time is None:
            log.warning('Skipping checkpoint consideration for record missing store-time: %s', record)
            continue
        parsed_store_time = parse_wasapi_datetime(store_time)
        if max_datetime is None or parsed_store_time > max_datetime:
            max_datetime = parsed_store_time
            max_store_time = store_time
    result = max_store_time
    return result


def get_next_page_number(page_payload: dict[str, object], current_page_number: int) -> int | None:
    """
    Determines the next page number from a WASAPI page payload.
    """
    result: int | None = None
    next_value = page_payload.get('next')
    if isinstance(next_value, str) and next_value:
        parsed_url = urlparse(next_value)
        page_values = parse_qs(parsed_url.query).get('page')
        if page_values and page_values[0].isdigit():
            result = int(page_values[0])
        elif next_value.isdigit():
            result = int(next_value)
    elif isinstance(next_value, int):
        result = next_value
    else:
        total_pages = page_payload.get('pages') or page_payload.get('total_pages') or page_payload.get('page_count')
        if isinstance(total_pages, int) and current_page_number < total_pages:
            result = current_page_number + 1
    return result


def build_payload_debug_summary(page_payload: dict[str, object], page_records: list[dict[str, object]]) -> dict[str, object]:
    """
    Builds a compact summary of one WASAPI response payload for debug logging.
    """
    result = {
        'keys': sorted(page_payload.keys()),
        'record_count': len(page_records),
        'count': page_payload.get('count'),
        'next': page_payload.get('next'),
        'previous': page_payload.get('previous'),
        'request_url': page_payload.get('request-url'),
    }
    return result


def fetch_collection_discovery(
    client: httpx.Client,
    base_url: str,
    collection_id: int,
    after_datetime: datetime,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> DiscoveryResult:
    """
    Fetches paginated WASAPI discovery records for one collection.
    """
    page_number = 1
    discovered_records: list[dict[str, object]] = []
    request_records: list[DiscoveryRequestRecord] = []
    after_datetime_utc = after_datetime.astimezone(UTC)
    formatted_after_datetime = format_wasapi_datetime(after_datetime_utc)

    while True:
        requested_at = datetime.now(UTC)
        params: dict[str, object] = {
            'collection': collection_id,
            'page': page_number,
            'page_size': page_size,
            'store-time-after': formatted_after_datetime,
        }
        response: httpx.Response | None = None
        try:
            response = client.get(base_url, params=params)
            log.debug(
                'Collection %s requested WASAPI page %s: %s params=%s',
                collection_id,
                page_number,
                response.request.url,
                params,
            )
            request_records.append(
                DiscoveryRequestRecord(
                    page_number=page_number,
                    requested_url=str(response.request.url),
                    requested_params=dict(params),
                    requested_at_utc=requested_at.isoformat(),
                    status_code=response.status_code,
                ),
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise WasapiDiscoveryError('WASAPI response JSON is not an object.')
            page_records = extract_discovery_records(payload)
            log.debug(
                'Collection %s page %s payload summary: %s',
                collection_id,
                page_number,
                build_payload_debug_summary(payload, page_records),
            )
            log.debug(
                'Collection %s page %s full payload: %s',
                collection_id,
                page_number,
                json.dumps(payload, sort_keys=True),
            )
            discovered_records.extend(page_records)
            next_page_number = get_next_page_number(payload, page_number)
            if next_page_number is None:
                break
            page_number = next_page_number
        except Exception as exc:
            if response is None:
                request_records.append(
                    DiscoveryRequestRecord(
                        page_number=page_number,
                        requested_url=base_url,
                        requested_params=dict(params),
                        requested_at_utc=requested_at.isoformat(),
                        status_code=None,
                    ),
                )
            partial_result = DiscoveryResult(
                collection_id=collection_id,
                after_datetime=after_datetime_utc,
                records=list(discovered_records),
                request_records=list(request_records),
                completed_successfully=False,
                max_observed_store_time=None,
            )
            if isinstance(exc, WasapiDiscoveryError):
                raise WasapiDiscoveryError(str(exc), partial_result) from exc
            raise WasapiDiscoveryError(
                f'Failed fetching collection {collection_id} page {page_number}: {exc}', partial_result
            ) from exc

    max_store_time = compute_max_store_time(discovered_records)
    result = DiscoveryResult(
        collection_id=collection_id,
        after_datetime=after_datetime_utc,
        records=discovered_records,
        request_records=request_records,
        completed_successfully=True,
        max_observed_store_time=max_store_time,
    )
    return result
