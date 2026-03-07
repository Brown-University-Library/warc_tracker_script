import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import TestCase

import httpx

sys.path.append(str(Path(__file__).parent.parent))

from lib.wasapi_discovery import (
    WasapiDiscoveryError,
    compute_store_time_after_datetime,
    extract_record_store_time,
    fetch_collection_discovery,
)


class FakeResponse:
    """
    Represents a lightweight fake httpx response for tests.
    """

    def __init__(self, url: str, payload: object, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.request = httpx.Request('GET', url)

    def raise_for_status(self) -> None:
        """
        Checks the fake response status code.
        """
        if self.status_code >= 400:
            raise httpx.HTTPStatusError('error', request=self.request, response=self)

    def json(self) -> object:
        """
        Returns the configured JSON payload.
        """
        result = self._payload
        return result


class FakeClient:
    """
    Represents a fake client returning pre-seeded page payloads.
    """

    def __init__(self, responses: list[FakeResponse]):
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, params: dict[str, object]) -> FakeResponse:
        """
        Returns the next fake response and records the request params.
        """
        self.calls.append({'url': url, 'params': dict(params)})
        if not self.responses:
            raise AssertionError('No fake responses remaining.')
        result = self.responses.pop(0)
        return result


class TestComputeStoreTimeAfterDatetime(TestCase):
    """
    Test cases for overlap-window boundary computation.
    """

    def test_uses_checkpoint_when_present(self):
        """
        Checks that the checkpoint value is used as the overlap reference.
        """
        now = datetime(2026, 3, 6, 12, 0, 0, tzinfo=UTC)

        result = compute_store_time_after_datetime('2026-02-20T15:30:00Z', now)

        self.assertEqual(result, datetime(2026, 1, 21, 15, 30, 0, tzinfo=UTC))

    def test_uses_now_when_checkpoint_missing(self):
        """
        Checks that now is used when no checkpoint exists.
        """
        now = datetime(2026, 3, 6, 12, 0, 0, tzinfo=UTC)

        result = compute_store_time_after_datetime(None, now)

        self.assertEqual(result, datetime(2026, 2, 4, 12, 0, 0, tzinfo=UTC))


class TestExtractRecordStoreTime(TestCase):
    """
    Test cases for record store-time extraction.
    """

    def test_returns_store_time_when_present(self):
        """
        Checks that a valid store-time string is returned.
        """
        result = extract_record_store_time({'store-time': '2026-03-01T00:00:00Z'})
        self.assertEqual(result, '2026-03-01T00:00:00Z')

    def test_returns_none_when_missing(self):
        """
        Checks that missing store-time returns None.
        """
        result = extract_record_store_time({'filename': 'alpha.warc.gz'})
        self.assertIsNone(result)


class TestFetchCollectionDiscovery(TestCase):
    """
    Test cases for paginated WASAPI discovery.
    """

    def test_first_run_without_boundary_omits_store_time_after_param(self):
        """
        Checks that first-run discovery does not send a store-time-after filter.
        """
        client = FakeClient(
            [
                FakeResponse(
                    'https://example.org/wasapi?page=1',
                    {
                        'results': [
                            {'filename': 'alpha.warc.gz', 'store-time': '2026-02-01T01:00:00Z'},
                        ],
                        'next': None,
                    },
                ),
            ],
        )

        result = fetch_collection_discovery(
            client=client,
            base_url='https://example.org/wasapi',
            collection_id=123,
            after_datetime=None,
            page_size=50,
        )

        self.assertTrue(result.completed_successfully)
        self.assertIsNone(result.after_datetime)
        self.assertNotIn('store-time-after', client.calls[0]['params'])

    def test_pagination_happy_path(self):
        """
        Checks that multiple pages are combined and max store-time is computed.
        """
        client = FakeClient(
            [
                FakeResponse(
                    'https://example.org/wasapi?page=1',
                    {
                        'results': [
                            {'filename': 'alpha.warc.gz', 'store-time': '2026-02-01T01:00:00Z'},
                        ],
                        'next': 'https://example.org/wasapi?page=2',
                    },
                ),
                FakeResponse(
                    'https://example.org/wasapi?page=2',
                    {
                        'results': [
                            {'filename': 'beta.warc.gz', 'store-time': '2026-02-03T09:15:00Z'},
                        ],
                        'next': None,
                    },
                ),
            ],
        )
        after_datetime = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

        result = fetch_collection_discovery(
            client=client,
            base_url='https://example.org/wasapi',
            collection_id=123,
            after_datetime=after_datetime,
            page_size=50,
        )

        self.assertTrue(result.completed_successfully)
        self.assertEqual(result.collection_id, 123)
        self.assertEqual(result.after_datetime, after_datetime)
        self.assertEqual(len(result.records), 2)
        self.assertEqual(result.max_observed_store_time, '2026-02-03T09:15:00Z')
        self.assertEqual(len(result.request_records), 2)
        self.assertEqual(client.calls[0]['params']['store-time-after'], '2026-01-01T00:00:00Z')
        self.assertEqual(client.calls[0]['params']['page_size'], 50)

    def test_missing_store_time_does_not_break_enumeration(self):
        """
        Checks that records without store-time are tolerated and ignored for checkpoint max.
        """
        client = FakeClient(
            [
                FakeResponse(
                    'https://example.org/wasapi?page=1',
                    {
                        'results': [
                            {'filename': 'alpha.warc.gz'},
                            {'filename': 'beta.warc.gz', 'store-time': '2026-02-03T09:15:00Z'},
                        ],
                        'next': None,
                    },
                ),
            ],
        )

        result = fetch_collection_discovery(
            client=client,
            base_url='https://example.org/wasapi',
            collection_id=123,
            after_datetime=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
            page_size=100,
        )

        self.assertTrue(result.completed_successfully)
        self.assertEqual(len(result.records), 2)
        self.assertEqual(result.max_observed_store_time, '2026-02-03T09:15:00Z')

    def test_malformed_response_raises_clear_error(self):
        """
        Checks that a non-object JSON payload raises a discovery error.
        """
        client = FakeClient(
            [
                FakeResponse('https://example.org/wasapi?page=1', ['not', 'an', 'object']),
            ],
        )

        with self.assertRaises(WasapiDiscoveryError) as context:
            fetch_collection_discovery(
                client=client,
                base_url='https://example.org/wasapi',
                collection_id=123,
                after_datetime=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
                page_size=100,
            )

        self.assertIn('not an object', str(context.exception))
        self.assertIsNotNone(context.exception.partial_result)
        self.assertFalse(context.exception.partial_result.completed_successfully)


if __name__ == '__main__':
    unittest.main()
