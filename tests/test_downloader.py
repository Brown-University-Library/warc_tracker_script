import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

import httpx

sys.path.append(str(Path(__file__).parent.parent))

from lib.collection_sheet import CollectionJob, HeaderLocation
from lib.downloader import build_partial_download_path, download_to_path
from lib.orchestration import build_planned_downloads, process_collection_job


class TestBuildPartialDownloadPath(TestCase):
    """
    Test cases for partial-download path construction.
    """

    def test_appends_partial_suffix(self):
        """
        Checks that the partial path appends the `.partial` suffix.
        """
        destination_path = Path('/tmp/example/file.warc.gz')

        result = build_partial_download_path(destination_path)

        self.assertEqual(result, Path('/tmp/example/file.warc.gz.partial'))


class TestDownloadToPath(TestCase):
    """
    Test cases for streamed file downloading.
    """

    def test_writes_streamed_bytes_and_atomically_renames_on_success(self):
        """
        Checks that streamed content lands at the final path with no leftover partial file.
        """
        chunks = [b'alpha-', b'beta']

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b''.join(chunks), request=request)

        transport = httpx.MockTransport(handler)
        with tempfile.TemporaryDirectory() as temp_dir:
            destination_path = Path(temp_dir) / 'nested' / 'file.warc.gz'
            with httpx.Client(transport=transport) as client:
                result = download_to_path(client, 'https://example.org/file.warc.gz', destination_path, chunk_size=3)

            self.assertTrue(result.success)
            self.assertEqual(result.bytes_written, len(b''.join(chunks)))
            self.assertTrue(destination_path.exists())
            self.assertEqual(destination_path.read_bytes(), b''.join(chunks))
            self.assertFalse(result.partial_path.exists())

    def test_removes_stale_partial_before_retry(self):
        """
        Checks that a stale partial file is overwritten by a fresh download attempt.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b'fresh-bytes', request=request)

        transport = httpx.MockTransport(handler)
        with tempfile.TemporaryDirectory() as temp_dir:
            destination_path = Path(temp_dir) / 'retry' / 'file.warc.gz'
            partial_path = build_partial_download_path(destination_path)
            partial_path.parent.mkdir(parents=True, exist_ok=True)
            partial_path.write_bytes(b'stale-bytes')

            with httpx.Client(transport=transport) as client:
                result = download_to_path(client, 'https://example.org/file.warc.gz', destination_path)

            self.assertTrue(result.success)
            self.assertTrue(destination_path.exists())
            self.assertEqual(destination_path.read_bytes(), b'fresh-bytes')
            self.assertFalse(partial_path.exists())

    def test_returns_failure_and_cleans_up_partial_on_http_error(self):
        """
        Checks that HTTP failure leaves no misleading completed file behind.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, content=b'missing', request=request)

        transport = httpx.MockTransport(handler)
        with tempfile.TemporaryDirectory() as temp_dir:
            destination_path = Path(temp_dir) / 'failure' / 'file.warc.gz'
            with httpx.Client(transport=transport) as client:
                result = download_to_path(client, 'https://example.org/file.warc.gz', destination_path)

            self.assertFalse(result.success)
            self.assertFalse(destination_path.exists())
            self.assertFalse(result.partial_path.exists())
            self.assertIn('404', result.error_message)


class TestOrchestrationDownloadConsumption(TestCase):
    """
    Test cases for orchestration consumption of the downloader layer.
    """

    def test_build_planned_downloads_skips_record_without_usable_source_url(self):
        """
        Checks that records missing a source URL are skipped cleanly.
        """
        discovered_records = [
            {
                'filename': 'ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz',
                'locations': ['https://example.org/alpha.warc.gz'],
            },
            {
                'filename': 'ARCHIVEIT-123-20260306123556-00000-beta.warc.gz',
            },
        ]

        result = build_planned_downloads(Path('/tmp/storage'), 123, discovered_records)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].filename, 'ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz')
        self.assertEqual(result[0].source_url, 'https://example.org/alpha.warc.gz')

    def test_process_collection_job_invokes_downloader_for_usable_records(self):
        """
        Checks that sequential orchestration invokes the downloader for records with planned destinations.
        """
        collection_job = CollectionJob(
            collection_id=123,
            repository='UA',
            collection_url='https://example.com',
            collection_name='Example',
            row_number=7,
        )
        client = MagicMock(spec=httpx.Client)
        worksheet = MagicMock()
        header_location = HeaderLocation(
            header_row_index=1,
            column_map={
                'processing_status_main': 0,
                'processing_status_detail': 1,
                'summary_status_last_wasapi_check': 2,
                'summary_status_downloaded_warcs_count': 3,
                'summary_status_downloaded': 4,
                'summary_status_server_path': 5,
            },
        )
        discovery_result = MagicMock()
        discovery_result.records = [
            {
                'filename': 'ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz',
                'locations': ['https://example.org/alpha.warc.gz'],
            },
            {
                'filename': 'ARCHIVEIT-123-20260306123556-00000-beta.warc.gz',
            },
        ]
        discovery_result.request_records = [{'page': 1}]
        discovery_result.completed_successfully = True
        discovery_result.max_observed_store_time = '2026-03-06T12:00:00Z'
        download_result = MagicMock()
        download_result.success = True
        download_result.bytes_written = 11
        download_result.destination_path = Path('/tmp/storage/collections/123/warcs/2026/03/file.warc.gz')

        with (
            patch(
                'lib.orchestration.load_collection_state',
                return_value={'enumeration_checkpoint_store_time_max': None, 'files': {}},
            ),
            patch('lib.orchestration.compute_store_time_after_datetime') as mock_compute,
            patch('lib.orchestration.fetch_collection_discovery', return_value=discovery_result),
            patch('lib.orchestration.save_collection_state'),
            patch('lib.orchestration.log_planned_download_paths'),
            patch('lib.orchestration.download_to_path', return_value=download_result) as mock_download,
            patch('lib.orchestration.log_collection_download_summary') as mock_log_summary,
            patch('lib.orchestration.update_collection_processing_status'),
            patch('lib.orchestration.update_collection_final_reporting'),
            patch('lib.orchestration.datetime') as mock_datetime,
        ):
            mock_compute.return_value = datetime(2026, 2, 1, 0, 0, 0, tzinfo=UTC)
            mock_datetime.now.return_value = datetime(2026, 3, 7, 15, 0, 0, tzinfo=UTC)
            process_collection_job(
                client,
                collection_job,
                Path('/tmp/storage'),
                'https://example.org/wasapi',
                worksheet,
                header_location,
            )

        self.assertEqual(mock_download.call_count, 1)
        self.assertEqual(mock_download.call_args.args[1], 'https://example.org/alpha.warc.gz')
        self.assertTrue(
            str(mock_download.call_args.args[2]).endswith(
                '/collections/123/warcs/2026/03/ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz'
            )
        )
        self.assertEqual(mock_log_summary.call_args.args[2], 1)


if __name__ == '__main__':
    unittest.main()
