import os
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

import httpx

sys.path.append(str(Path(__file__).parent.parent))

from lib.collection_sheet import CollectionJob, HeaderLocation
from lib.fixity import FixityResult
from lib.orchestration import (
    STATUS_COMPLETED_WITH_SOME_FILE_FAILURES,
    STATUS_DOWNLOADED_WITHOUT_ERRORS,
    build_collection_failure_report,
    build_collection_final_report,
    build_planned_download_paths,
    build_planned_downloads,
    count_pending_download_candidates,
    get_archive_it_credentials,
    get_downloaded_storage_root,
    get_record_source_url,
    process_collection_job,
)


class TestGetStorageRoot(TestCase):
    """
    Test cases for storage-root configuration.
    """

    def test_uses_env_value_when_present(self):
        """
        Checks that the configured storage root comes from the environment.
        """
        with patch.dict(os.environ, {'WARC_STORAGE_ROOT': '~/warc-root'}, clear=False):
            result = get_downloaded_storage_root()

        self.assertEqual(result, Path('~/warc-root').expanduser())


class TestGetArchiveItCredentials(TestCase):
    """
    Test cases for Archive-It credential lookup.
    """

    def test_returns_primary_credential_names(self):
        """
        Checks that primary WASAPI credential variable names are preferred.
        """
        with patch.dict(
            os.environ,
            {
                'ARCHIVEIT_WASAPI_USERNAME': 'user-a',
                'ARCHIVEIT_WASAPI_PASSWORD': 'pass-a',
            },
            clear=True,
        ):
            result = get_archive_it_credentials()

        self.assertEqual(result, ('user-a', 'pass-a'))

    def test_returns_none_when_missing(self):
        """
        Checks that missing credentials return None.
        """
        with patch.dict(os.environ, {}, clear=True):
            result = get_archive_it_credentials()

        self.assertIsNone(result)


class TestCountPendingDownloadCandidates(TestCase):
    """
    Test cases for pending-download counting.
    """

    def test_counts_only_non_downloaded_filename_records(self):
        """
        Checks that only filename-bearing records without downloaded status are counted.
        """
        discovered_records = [
            {'filename': 'alpha.warc.gz'},
            {'filename': 'beta.warc.gz'},
            {'filename': 'gamma.warc.gz'},
            {'store-time': '2026-03-01T00:00:00Z'},
        ]
        state = {
            'files': {
                'beta.warc.gz': {'status': 'downloaded'},
                'gamma.warc.gz': {'status': 'failed'},
            },
        }

        result = count_pending_download_candidates(discovered_records, state)

        self.assertEqual(result, 2)


class TestBuildPlannedDownloadPaths(TestCase):
    """
    Test cases for planned local destination-path building.
    """

    def test_builds_paths_for_records_with_usable_filenames(self):
        """
        Checks that filename-bearing records become planned WARC and fixity destinations.
        """
        discovered_records = [
            {'filename': 'ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz'},
            {'filename': '   '},
            {'store-time': '2026-03-01T00:00:00Z'},
        ]

        result = build_planned_download_paths(Path('/tmp/storage'), 123, discovered_records)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].year, '2026')
        self.assertEqual(result[0].month, '03')
        self.assertTrue(
            str(result[0].warc_path).endswith(
                '/collections/123/warcs/2026/03/ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz'
            )
        )

    def test_skips_records_with_invalid_filenames(self):
        """
        Checks that invalid filenames are skipped instead of breaking orchestration.
        """
        discovered_records = [
            {'filename': 'not-a-parseable-warc-name.warc.gz'},
        ]

        with patch('lib.orchestration.log.exception') as mock_log_exception:
            result = build_planned_download_paths(Path('/tmp/storage'), 123, discovered_records)

        self.assertEqual(result, [])
        self.assertTrue(mock_log_exception.called)


class TestDownloadPlanningHelpers(TestCase):
    """
    Test cases for source-url extraction and download planning.
    """

    def test_get_record_source_url_prefers_locations(self):
        """
        Checks that source-url extraction uses the first usable locations entry.
        """
        record = {
            'filename': 'ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz',
            'locations': ['https://example.org/alpha.warc.gz', 'https://example.org/alpha-backup.warc.gz'],
            'url': 'https://example.org/fallback.warc.gz',
        }

        result = get_record_source_url(record)

        self.assertEqual(result, 'https://example.org/alpha.warc.gz')

    def test_build_planned_downloads_skips_records_without_source_url(self):
        """
        Checks that only records with both filename and usable source URL become planned downloads.
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


class TestProcessCollectionJob(TestCase):
    """
    Test cases for per-collection orchestration.
    """

    def test_updates_checkpoint_when_discovery_succeeds(self):
        """
        Checks that successful discovery persists the updated checkpoint.
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
                'summary_status_downloaded_warcs_size': 4,
                'summary_status_server_path': 5,
            },
        )
        discovery_result = MagicMock()
        discovery_result.records = [
            {
                'filename': 'ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz',
                'locations': ['https://example.org/alpha.warc.gz'],
            }
        ]
        discovery_result.request_records = [{'page': 1}]
        discovery_result.completed_successfully = True
        discovery_result.max_observed_store_time = '2026-03-06T12:00:00Z'
        download_result = MagicMock()
        download_result.success = True
        download_result.bytes_written = 11
        download_result.destination_path = Path('/tmp/storage/collections/123/warcs/2026/03/file.warc.gz')
        fixity_result = FixityResult(
            success=True,
            warc_path=download_result.destination_path,
            sha256_path=Path('/tmp/storage/collections/123/fixity/2026/03/file.warc.gz.sha256'),
            json_path=Path('/tmp/storage/collections/123/fixity/2026/03/file.warc.gz.json'),
            sha256_hexdigest='abc123',
            size=11,
            source_url='https://example.org/alpha.warc.gz',
            completed_at='2026-03-06T12:34:56+00:00',
            error_message=None,
        )

        with (
            patch(
                'lib.orchestration.load_collection_state',
                return_value={'enumeration_checkpoint_store_time_max': None, 'files': {}},
            ),
            patch('lib.orchestration.compute_store_time_after_datetime') as mock_compute,
            patch('lib.orchestration.fetch_collection_discovery', return_value=discovery_result),
            patch('lib.orchestration.save_collection_state') as mock_save,
            patch('lib.orchestration.build_planned_download_paths', return_value=['planned-path']) as mock_build_paths,
            patch('lib.orchestration.log_planned_download_paths') as mock_log_paths,
            patch('lib.orchestration.download_to_path', return_value=download_result) as mock_download,
            patch('lib.orchestration.write_fixity_sidecars', return_value=fixity_result) as mock_fixity,
            patch('lib.orchestration.log_collection_download_summary') as mock_log_summary,
            patch('lib.orchestration.update_collection_processing_status') as mock_update_status,
            patch('lib.orchestration.update_collection_final_reporting') as mock_final_reporting,
            patch('lib.orchestration.datetime') as mock_datetime,
        ):
            mock_compute.return_value = datetime(2026, 2, 1, 0, 0, 0, tzinfo=UTC)
            mock_datetime.now.return_value = datetime(2026, 3, 7, 15, 0, 0, tzinfo=UTC)
            result = process_collection_job(
                client,
                collection_job,
                Path('/tmp/storage'),
                'https://example.org/wasapi',
                worksheet,
                header_location,
            )

        saved_state = mock_save.call_args.args[2]
        self.assertEqual(saved_state['enumeration_checkpoint_store_time_max'], '2026-03-06T12:00:00Z')
        self.assertEqual(mock_build_paths.call_args.args[1], 123)
        self.assertEqual(mock_log_paths.call_args.args[1], ['planned-path'])
        self.assertEqual(mock_download.call_count, 1)
        self.assertEqual(mock_fixity.call_count, 1)
        self.assertEqual(mock_log_summary.call_args.args[1], 1)
        self.assertEqual(mock_log_summary.call_args.args[2], 1)
        self.assertEqual(mock_log_summary.call_args.args[4], [fixity_result])
        self.assertEqual(mock_update_status.call_args.args[2], 7)
        self.assertEqual(mock_final_reporting.call_args.args[2], 7)
        self.assertEqual(result.status_update.processing_status_main, STATUS_DOWNLOADED_WITHOUT_ERRORS)
        self.assertEqual(result.summary_update.summary_status_downloaded_warcs_count, '1')
        self.assertEqual(result.summary_update.summary_status_downloaded_warcs_size, '11')

    def test_skips_checkpoint_save_when_discovery_not_complete(self):
        """
        Checks that incomplete discovery does not persist a new checkpoint.
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
                'summary_status_downloaded_warcs_size': 4,
                'summary_status_server_path': 5,
            },
        )
        discovery_result = MagicMock()
        discovery_result.records = [
            {
                'filename': 'ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz',
                'locations': ['https://example.org/alpha.warc.gz'],
            }
        ]
        discovery_result.request_records = [{'page': 1}]
        discovery_result.completed_successfully = False
        discovery_result.max_observed_store_time = '2026-03-06T12:00:00Z'
        download_result = MagicMock()
        download_result.success = True
        download_result.bytes_written = 11
        download_result.destination_path = Path('/tmp/storage/collections/123/warcs/2026/03/file.warc.gz')
        fixity_result = FixityResult(
            success=True,
            warc_path=download_result.destination_path,
            sha256_path=Path('/tmp/storage/collections/123/fixity/2026/03/file.warc.gz.sha256'),
            json_path=Path('/tmp/storage/collections/123/fixity/2026/03/file.warc.gz.json'),
            sha256_hexdigest='abc123',
            size=11,
            source_url='https://example.org/alpha.warc.gz',
            completed_at='2026-03-06T12:34:56+00:00',
            error_message=None,
        )

        with (
            patch(
                'lib.orchestration.load_collection_state',
                return_value={'enumeration_checkpoint_store_time_max': None, 'files': {}},
            ),
            patch('lib.orchestration.compute_store_time_after_datetime') as mock_compute,
            patch('lib.orchestration.fetch_collection_discovery', return_value=discovery_result),
            patch('lib.orchestration.save_collection_state') as mock_save,
            patch('lib.orchestration.build_planned_download_paths', return_value=['planned-path']) as mock_build_paths,
            patch('lib.orchestration.log_planned_download_paths') as mock_log_paths,
            patch('lib.orchestration.download_to_path', return_value=download_result) as mock_download,
            patch('lib.orchestration.write_fixity_sidecars', return_value=fixity_result) as mock_fixity,
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

        saved_states = [call.args[2] for call in mock_save.call_args_list]
        self.assertGreaterEqual(len(saved_states), 2)
        self.assertEqual(saved_states[0]['enumeration_checkpoint_store_time_max'], None)
        self.assertEqual(mock_build_paths.call_args.args[1], 123)
        self.assertEqual(mock_log_paths.call_args.args[1], ['planned-path'])
        self.assertEqual(mock_download.call_count, 1)
        self.assertEqual(mock_fixity.call_count, 1)
        self.assertEqual(mock_log_summary.call_args.args[1], 1)
        self.assertEqual(mock_log_summary.call_args.args[2], 1)
        self.assertEqual(mock_log_summary.call_args.args[4], [fixity_result])

    def test_failed_download_does_not_attempt_fixity_generation(self):
        """
        Checks that failed downloads do not invoke fixity generation.
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
                'summary_status_downloaded_warcs_size': 4,
                'summary_status_server_path': 5,
            },
        )
        discovery_result = MagicMock()
        discovery_result.records = [
            {
                'filename': 'ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz',
                'locations': ['https://example.org/alpha.warc.gz'],
            }
        ]
        discovery_result.request_records = [{'page': 1}]
        discovery_result.completed_successfully = True
        discovery_result.max_observed_store_time = '2026-03-06T12:00:00Z'
        download_result = MagicMock()
        download_result.success = False
        download_result.bytes_written = 0
        download_result.destination_path = Path('/tmp/storage/collections/123/warcs/2026/03/file.warc.gz')
        download_result.error_message = '404 Not Found'

        with (
            patch(
                'lib.orchestration.load_collection_state',
                return_value={'enumeration_checkpoint_store_time_max': None, 'files': {}},
            ),
            patch('lib.orchestration.compute_store_time_after_datetime') as mock_compute,
            patch('lib.orchestration.fetch_collection_discovery', return_value=discovery_result),
            patch('lib.orchestration.save_collection_state'),
            patch('lib.orchestration.build_planned_download_paths', return_value=['planned-path']),
            patch('lib.orchestration.log_planned_download_paths'),
            patch('lib.orchestration.download_to_path', return_value=download_result),
            patch('lib.orchestration.write_fixity_sidecars') as mock_fixity,
            patch('lib.orchestration.log_collection_download_summary') as mock_log_summary,
            patch('lib.orchestration.update_collection_processing_status'),
            patch('lib.orchestration.update_collection_final_reporting'),
            patch('lib.orchestration.datetime') as mock_datetime,
        ):
            mock_compute.return_value = datetime(2026, 2, 1, 0, 0, 0, tzinfo=UTC)
            mock_datetime.now.return_value = datetime(2026, 3, 7, 15, 0, 0, tzinfo=UTC)
            result = process_collection_job(
                client,
                collection_job,
                Path('/tmp/storage'),
                'https://example.org/wasapi',
                worksheet,
                header_location,
            )

        self.assertFalse(mock_fixity.called)
        self.assertEqual(mock_log_summary.call_args.args[3], [download_result])
        self.assertEqual(mock_log_summary.call_args.args[4], [])
        self.assertEqual(result.status_update.processing_status_main, STATUS_COMPLETED_WITH_SOME_FILE_FAILURES)


class TestCollectionReportingHelpers(TestCase):
    """
    Test cases for final spreadsheet reporting helper payloads.
    """

    def test_build_collection_final_report_for_file_failures(self):
        """
        Checks that file failures map to the expected final collection status.
        """
        collection_job = CollectionJob(123, 'UA', 'https://example.com', 'Example', 7)
        failed_download = MagicMock()
        failed_download.success = False

        result = build_collection_final_report(
            storage_root=Path('/tmp/storage'),
            collection_job=collection_job,
            discovery_completed_at='2026-03-07T15:00:00+00:00',
            planned_downloads=[MagicMock()],
            download_results=[failed_download],
            fixity_results=[],
        )

        self.assertEqual(result.status_update.processing_status_main, STATUS_COMPLETED_WITH_SOME_FILE_FAILURES)
        self.assertEqual(result.summary_update.summary_status_downloaded_warcs_size, '0')

    def test_build_collection_failure_report_for_discovery_failure(self):
        """
        Checks that discovery failure helper builds a clear final reporting payload.
        """
        collection_job = CollectionJob(123, 'UA', 'https://example.com', 'Example', 7)

        result = build_collection_failure_report(
            storage_root=Path('/tmp/storage'),
            collection_job=collection_job,
            status_main='discovery-failed',
            status_detail='discovery failed after 2 partial records',
            reported_at='2026-03-07T15:00:00+00:00',
        )

        self.assertEqual(result.status_update.processing_status_main, 'discovery-failed')
        self.assertEqual(result.status_update.processing_status_detail, 'discovery failed after 2 partial records')
        self.assertEqual(result.summary_update.summary_status_server_path, '/tmp/storage/collections/123')


if __name__ == '__main__':
    unittest.main()
