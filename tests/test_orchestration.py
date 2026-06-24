import hashlib
import json
import os
import sys
import unittest
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

import httpx

sys.path.append(str(Path(__file__).parent.parent))

from lib.collection_sheet import CollectionJob, HeaderLocation
from lib.fixity import FixityResult
from lib.orchestration import (
    BLOCKING_COORDINATION_STATUSES,
    DISCOVERY_MODE_FULL_BACKFILL_FIRST_RUN,
    DISCOVERY_MODE_INCREMENTAL_OVERLAP_WINDOW,
    RUN_COORDINATION_MODE_SKIP_SPREADSHEET_COORDINATION_CHECK,
    STATUS_COMPLETED_WITH_SOME_FILE_FAILURES,
    STATUS_DISCOVERY_IN_PROGRESS,
    STATUS_DOWNLOADED_WITHOUT_ERRORS,
    STATUS_DOWNLOADING_IN_PROGRESS,
    STATUS_DOWNLOAD_PLANNING_COMPLETE,
    STATUS_NO_NEW_FILES_TO_DOWNLOAD,
    DevCollectionsConfigurationError,
    PlannedDownload,
    RunCoordinationError,
    build_collection_failure_report,
    build_collection_final_report,
    build_download_progress_detail,
    build_evaluated_active_downloads,
    build_planned_download_paths,
    build_planned_downloads,
    build_reconciliation_retry_downloads,
    count_discovered_warc_filename_records,
    count_pending_download_candidates,
    determine_collection_discovery_mode,
    enforce_startup_run_coordination,
    format_local_display_timestamp,
    get_archive_it_credentials,
    get_blocking_coordination_summary,
    get_dev_collection_ids,
    get_download_progress_file_interval_update,
    get_downloaded_storage_root,
    get_record_source_url,
    get_run_coordination_mode,
    merge_planned_downloads,
    parse_dev_collection_ids,
    process_collection_job,
    resolve_collection_jobs_for_run,
    run_planned_downloads,
    should_skip_spreadsheet_coordination_check,
)


class TestGetStorageRoot(TestCase):
    """
    Test cases for storage-root configuration.
    """

    def test_uses_env_value_when_present(self) -> None:
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

    def test_returns_primary_credential_names(self) -> None:
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

    def test_returns_none_when_missing(self) -> None:
        """
        Checks that missing credentials return None.
        """
        with patch.dict(os.environ, {}, clear=True):
            result = get_archive_it_credentials()

        self.assertIsNone(result)


class TestRunCoordinationHelpers(TestCase):
    """
    Test cases for startup run coordination helpers.
    """

    def test_get_run_coordination_mode_returns_exact_non_blank_value(self) -> None:
        """
        Checks that coordination mode returns the configured non-blank string.
        """
        with patch.dict(
            os.environ,
            {'RUN_COORDINATION_MODE': RUN_COORDINATION_MODE_SKIP_SPREADSHEET_COORDINATION_CHECK},
            clear=True,
        ):
            result = get_run_coordination_mode()

        self.assertEqual(result, RUN_COORDINATION_MODE_SKIP_SPREADSHEET_COORDINATION_CHECK)

    def test_get_dev_collection_ids_returns_none_when_unset_or_blank(self) -> None:
        """
        Checks that DEV_COLLECTIONS is optional and blank values are ignored.
        """
        with patch.dict(os.environ, {}, clear=True):
            unset_result = get_dev_collection_ids()
        with patch.dict(os.environ, {'DEV_COLLECTIONS': '   '}, clear=True):
            blank_result = get_dev_collection_ids()

        self.assertIsNone(unset_result)
        self.assertIsNone(blank_result)

    def test_parse_dev_collection_ids_accepts_commas_spaces_and_deduplicates(self) -> None:
        """
        Checks that DEV_COLLECTIONS accepts comma and whitespace separators while preserving first-seen order.
        """
        result = parse_dev_collection_ids('22900, 15887 22900')

        self.assertEqual(result, [22900, 15887])

    def test_parse_dev_collection_ids_rejects_invalid_tokens(self) -> None:
        """
        Checks that invalid DEV_COLLECTIONS entries fail with a clear configuration error.
        """
        with self.assertRaises(DevCollectionsConfigurationError) as exc_context:
            parse_dev_collection_ids('22900,not-an-id')

        self.assertIn('not-an-id', str(exc_context.exception))

    def test_resolve_collection_jobs_for_run_preserves_job_metadata_for_requested_ids(self) -> None:
        """
        Checks that requested collection ids resolve back to the active CollectionJob objects from the spreadsheet.
        """
        active_collection_jobs = [
            CollectionJob(22900, 'MS', 'https://example.com/22900', 'Alpha', 4),
            CollectionJob(15887, 'UA', 'https://example.com/15887', 'Beta', 7),
        ]

        result = resolve_collection_jobs_for_run(active_collection_jobs, [15887])

        self.assertEqual(result, [active_collection_jobs[1]])
        self.assertEqual(result[0].row_number, 7)

    def test_resolve_collection_jobs_for_run_rejects_missing_active_ids(self) -> None:
        """
        Checks that requested ids must be present among active spreadsheet collection jobs.
        """
        active_collection_jobs = [CollectionJob(22900, 'MS', 'https://example.com/22900', 'Alpha', 4)]

        with self.assertRaises(DevCollectionsConfigurationError) as exc_context:
            resolve_collection_jobs_for_run(active_collection_jobs, [15887])

        self.assertIn('15887', str(exc_context.exception))
        self.assertIn('active spreadsheet collection rows', str(exc_context.exception))

    def test_should_skip_spreadsheet_coordination_check_only_for_exact_skip_mode(self) -> None:
        """
        Checks that only the exact skip mode skips spreadsheet coordination preflight.
        """
        self.assertTrue(
            should_skip_spreadsheet_coordination_check(RUN_COORDINATION_MODE_SKIP_SPREADSHEET_COORDINATION_CHECK)
        )
        self.assertFalse(should_skip_spreadsheet_coordination_check('manual'))
        self.assertFalse(should_skip_spreadsheet_coordination_check(None))

    def test_get_blocking_coordination_summary_returns_none_for_blank_and_unknown_statuses(self) -> None:
        """
        Checks that blank and unrecognized spreadsheet statuses do not block startup.
        """
        header_location = HeaderLocation(
            header_row_index=1,
            column_map={
                'processing_status_main': 1,
                'processing_status_detail': 2,
            },
        )
        values = [
            ['Collection ID', 'processing_status_main', 'processing_status_detail'],
            ['123', '', ''],
            ['456', 'unexpected-status', ''],
        ]
        collection_jobs = [
            CollectionJob(123, 'UA', 'https://example.com/123', 'Alpha', 2),
            CollectionJob(456, 'UA', 'https://example.com/456', 'Beta', 3),
        ]

        result = get_blocking_coordination_summary(values, header_location, collection_jobs)

        self.assertIsNone(result)

    def test_enforce_startup_run_coordination_blocks_active_status_without_skip_mode(self) -> None:
        """
        Checks that a run is refused when an active in-progress spreadsheet status is present without skip mode.
        """
        header_location = HeaderLocation(
            header_row_index=1,
            column_map={
                'processing_status_main': 1,
                'processing_status_detail': 2,
            },
        )
        values = [
            ['Collection ID', 'processing_status_main', 'processing_status_detail'],
            ['123', STATUS_DISCOVERY_IN_PROGRESS, 'full historical backfill'],
            ['456', 'completed-with-some-file-failures', ''],
        ]
        collection_jobs = [
            CollectionJob(123, 'UA', 'https://example.com/123', 'Alpha', 2),
            CollectionJob(456, 'UA', 'https://example.com/456', 'Beta', 3),
        ]

        with self.assertRaises(RunCoordinationError) as exc_context:
            enforce_startup_run_coordination('manual', values, header_location, collection_jobs)

        self.assertIn('Runs must not start when spreadsheet in-progress statuses are present', str(exc_context.exception))
        self.assertIn(STATUS_DISCOVERY_IN_PROGRESS, str(exc_context.exception))
        self.assertIn('123', str(exc_context.exception))

    def test_enforce_startup_run_coordination_skips_blocking_check_for_skip_mode(self) -> None:
        """
        Checks that skip mode bypasses spreadsheet blocking statuses.
        """
        header_location = HeaderLocation(
            header_row_index=1,
            column_map={
                'processing_status_main': 1,
                'processing_status_detail': 2,
            },
        )
        values = [
            ['Collection ID', 'processing_status_main', 'processing_status_detail'],
            ['123', STATUS_DOWNLOADING_IN_PROGRESS, '40% (2/5 files)'],
        ]
        collection_jobs = [CollectionJob(123, 'UA', 'https://example.com/123', 'Alpha', 2)]

        result = enforce_startup_run_coordination(
            RUN_COORDINATION_MODE_SKIP_SPREADSHEET_COORDINATION_CHECK, values, header_location, collection_jobs
        )

        self.assertIsNone(result)
        self.assertEqual(
            BLOCKING_COORDINATION_STATUSES, frozenset((STATUS_DISCOVERY_IN_PROGRESS, STATUS_DOWNLOADING_IN_PROGRESS))
        )


class TestDisplayTimestampFormatting(TestCase):
    """
    Test cases for spreadsheet display timestamp formatting.
    """

    def test_format_local_display_timestamp_uses_seconds_precision(self) -> None:
        """
        Checks that spreadsheet display timestamps drop sub-second precision.
        """
        result = format_local_display_timestamp('2026-03-07T15:00:00.987654+00:00')

        self.assertNotIn('.987654', result)
        self.assertIn('T', result)


class TestCountPendingDownloadCandidates(TestCase):
    """
    Test cases for pending-download counting.
    """

    def test_counts_only_non_downloaded_filename_records(self) -> None:
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


class TestCountDiscoveredWarcFilenameRecords(TestCase):
    """
    Test cases for latest-fetch file-count reporting.
    """

    def test_counts_only_records_with_usable_filenames(self) -> None:
        """
        Checks that latest-fetch file count ignores records without usable filenames.
        """
        discovered_records = [
            {'filename': 'alpha.warc.gz'},
            {'filename': '  '},
            {'store-time': '2026-03-01T00:00:00Z'},
            {'filename': 'beta.warc.gz'},
        ]

        result = count_discovered_warc_filename_records(discovered_records)

        self.assertEqual(result, 2)


class TestBuildPlannedDownloadPaths(TestCase):
    """
    Test cases for planned local destination-path building.
    """

    def test_builds_paths_for_records_with_usable_filenames(self) -> None:
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
                '/collections/123/UNKNOWN_SEED/2026/03/ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz'
            )
        )

    def test_skips_records_with_invalid_filenames(self) -> None:
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

    def test_get_record_source_url_prefers_locations(self) -> None:
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

    def test_build_planned_downloads_skips_records_without_source_url(self) -> None:
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

    def test_build_reconciliation_retry_downloads_includes_missing_local_warc(self) -> None:
        """
        Checks that a manifest entry with a missing local WARC and usable source URL becomes a retry candidate.
        """
        state = {
            'files': {
                'ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz': {
                    'source_url': 'https://example.org/alpha.warc.gz',
                    'warc_path': '/tmp/storage/collections/123/UNKNOWN_SEED/2026/03/alpha.warc.gz',
                }
            }
        }

        result = build_reconciliation_retry_downloads(Path('/tmp/storage'), 123, state)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].filename, 'ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz')
        self.assertEqual(result[0].source_url, 'https://example.org/alpha.warc.gz')
        self.assertTrue(
            str(result[0].planned_paths.warc_path).endswith(
                '/collections/123/UNKNOWN_SEED/2026/03/ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz'
            )
        )

    def test_merge_planned_downloads_prefers_discovery_candidate_for_duplicate_filename(self) -> None:
        """
        Checks that discovery planning wins when the same filename appears in both candidate sources.
        """
        duplicate_filename = 'ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz'
        reconciliation_candidate = PlannedDownload(
            filename=duplicate_filename,
            source_url='https://example.org/reconciliation-alpha.warc.gz',
            planned_paths=build_planned_download_paths(Path('/tmp/storage'), 123, [{'filename': duplicate_filename}])[0],
        )
        discovery_candidate = PlannedDownload(
            filename=duplicate_filename,
            source_url='https://example.org/discovery-alpha.warc.gz',
            planned_paths=build_planned_download_paths(Path('/tmp/storage'), 123, [{'filename': duplicate_filename}])[0],
        )

        result = merge_planned_downloads([reconciliation_candidate], [discovery_candidate])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source_url, 'https://example.org/discovery-alpha.warc.gz')

    def test_build_evaluated_active_downloads_keeps_missing_warc_and_excludes_complete_file(self) -> None:
        """
        Checks that evaluation keeps a missing WARC active and excludes an already-complete local file.
        """
        with TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            missing_filename = 'ARCHIVEIT-123-20260306123456-00000-missing.warc.gz'
            complete_filename = 'ARCHIVEIT-123-20260306123556-00000-complete.warc.gz'
            missing_planned_download = PlannedDownload(
                filename=missing_filename,
                source_url='https://example.org/missing.warc.gz',
                planned_paths=build_planned_download_paths(storage_root, 123, [{'filename': missing_filename}])[0],
            )
            complete_planned_download = PlannedDownload(
                filename=complete_filename,
                source_url='https://example.org/complete.warc.gz',
                planned_paths=build_planned_download_paths(storage_root, 123, [{'filename': complete_filename}])[0],
            )
            content = b'complete-bytes'
            expected_digest = hashlib.sha256(content).hexdigest()
            complete_planned_download.planned_paths.warc_path.parent.mkdir(parents=True, exist_ok=True)
            complete_planned_download.planned_paths.warc_path.write_bytes(content)
            complete_planned_download.planned_paths.sha256_path.parent.mkdir(parents=True, exist_ok=True)
            complete_planned_download.planned_paths.sha256_path.write_text(
                f'{expected_digest} *{complete_planned_download.planned_paths.warc_path.name}\n',
                encoding='utf-8',
            )
            complete_planned_download.planned_paths.json_path.write_text(
                json.dumps(
                    {
                        'sha256': expected_digest,
                        'size': len(content),
                        'source_url': complete_planned_download.source_url,
                        'warc_filename': complete_planned_download.planned_paths.warc_path.name,
                        'warc_path': str(complete_planned_download.planned_paths.warc_path),
                    }
                ),
                encoding='utf-8',
            )
            state = {
                'files': {
                    complete_filename: {
                        'status': 'downloaded',
                        'json_path': str(complete_planned_download.planned_paths.json_path),
                    }
                }
            }

            active_downloads, reason_counts = build_evaluated_active_downloads(
                [missing_planned_download, complete_planned_download],
                state,
            )

        self.assertEqual([planned_download.filename for planned_download in active_downloads], [missing_filename])
        self.assertEqual(reason_counts['missing_warc'], 1)
        self.assertEqual(reason_counts['already_complete'], 1)

    def test_build_evaluated_active_downloads_keeps_missing_fixity_and_size_mismatch(self) -> None:
        """
        Checks that evaluation keeps candidates active for missing fixity and size mismatch conditions.
        """
        with TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            fixity_filename = 'ARCHIVEIT-123-20260306123456-00000-fixity.warc.gz'
            mismatch_filename = 'ARCHIVEIT-123-20260306123556-00000-size.warc.gz'
            fixity_planned_download = PlannedDownload(
                filename=fixity_filename,
                source_url='https://example.org/fixity.warc.gz',
                planned_paths=build_planned_download_paths(storage_root, 123, [{'filename': fixity_filename}])[0],
            )
            mismatch_planned_download = PlannedDownload(
                filename=mismatch_filename,
                source_url='https://example.org/size.warc.gz',
                planned_paths=build_planned_download_paths(storage_root, 123, [{'filename': mismatch_filename}])[0],
            )
            fixity_planned_download.planned_paths.warc_path.parent.mkdir(parents=True, exist_ok=True)
            fixity_planned_download.planned_paths.warc_path.write_bytes(b'fixity-bytes')
            mismatch_planned_download.planned_paths.warc_path.parent.mkdir(parents=True, exist_ok=True)
            mismatch_planned_download.planned_paths.warc_path.write_bytes(b'12345')
            state = {
                'files': {
                    mismatch_filename: {
                        'status': 'downloaded',
                        'size': 99,
                    }
                }
            }

            active_downloads, reason_counts = build_evaluated_active_downloads(
                [fixity_planned_download, mismatch_planned_download],
                state,
            )

        self.assertEqual(
            [planned_download.filename for planned_download in active_downloads],
            [fixity_filename, mismatch_filename],
        )
        self.assertEqual(reason_counts['missing_fixity'], 1)
        self.assertEqual(reason_counts['size_mismatch'], 1)

    def test_build_evaluated_active_downloads_keeps_retry_after_prior_failure(self) -> None:
        """
        Checks that evaluation keeps a prior failed manifest entry active even when local artifacts are otherwise complete.
        """
        with TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            filename = 'ARCHIVEIT-123-20260306123456-00000-retry.warc.gz'
            planned_download = PlannedDownload(
                filename=filename,
                source_url='https://example.org/retry.warc.gz',
                planned_paths=build_planned_download_paths(storage_root, 123, [{'filename': filename}])[0],
            )
            content = b'retry-bytes'
            expected_digest = hashlib.sha256(content).hexdigest()
            planned_download.planned_paths.warc_path.parent.mkdir(parents=True, exist_ok=True)
            planned_download.planned_paths.warc_path.write_bytes(content)
            planned_download.planned_paths.sha256_path.parent.mkdir(parents=True, exist_ok=True)
            planned_download.planned_paths.sha256_path.write_text(
                f'{expected_digest} *{planned_download.planned_paths.warc_path.name}\n',
                encoding='utf-8',
            )
            planned_download.planned_paths.json_path.write_text(
                json.dumps(
                    {
                        'sha256': expected_digest,
                        'size': len(content),
                        'source_url': planned_download.source_url,
                        'warc_filename': planned_download.planned_paths.warc_path.name,
                        'warc_path': str(planned_download.planned_paths.warc_path),
                    }
                ),
                encoding='utf-8',
            )
            state = {
                'files': {
                    filename: {
                        'status': 'failed',
                        'json_path': str(planned_download.planned_paths.json_path),
                    }
                }
            }

            active_downloads, reason_counts = build_evaluated_active_downloads([planned_download], state)

        self.assertEqual([planned_download.filename for planned_download in active_downloads], [filename])
        self.assertEqual(reason_counts['retry_after_prior_failure'], 1)


class TestProcessCollectionJob(TestCase):
    """
    Test cases for per-collection orchestration.
    """

    def test_determine_collection_discovery_mode_uses_full_backfill_without_checkpoint(self) -> None:
        """
        Checks that a missing checkpoint selects first-run full backfill mode.
        """
        now = datetime(2026, 3, 7, 15, 0, 0, tzinfo=UTC)

        discovery_mode, after_datetime = determine_collection_discovery_mode(None, now)

        self.assertEqual(discovery_mode, DISCOVERY_MODE_FULL_BACKFILL_FIRST_RUN)
        self.assertIsNone(after_datetime)

    def test_determine_collection_discovery_mode_uses_overlap_window_with_checkpoint(self) -> None:
        """
        Checks that a checkpoint selects incremental overlap-window mode.
        """
        now = datetime(2026, 3, 7, 15, 0, 0, tzinfo=UTC)

        discovery_mode, after_datetime = determine_collection_discovery_mode('2026-03-01T12:00:00Z', now)

        self.assertEqual(discovery_mode, DISCOVERY_MODE_INCREMENTAL_OVERLAP_WINDOW)
        self.assertEqual(after_datetime, datetime(2026, 1, 30, 12, 0, 0, tzinfo=UTC))

    def test_updates_checkpoint_when_discovery_succeeds(self) -> None:
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
        download_result.destination_path = Path('/tmp/storage/collections/123/UNKNOWN_SEED/2026/03/file.warc.gz')
        fixity_result = FixityResult(
            success=True,
            warc_path=download_result.destination_path,
            sha256_path=Path('/tmp/storage/collections/123/UNKNOWN_SEED/2026/03/file.warc.gz.sha256'),
            json_path=Path('/tmp/storage/collections/123/UNKNOWN_SEED/2026/03/file.warc.gz.json'),
            sha256_hexdigest='abc123',
            size=11,
            source_url='https://example.org/alpha.warc.gz',
            completed_at='2026-03-06T12:34:56+00:00',
            error_message=None,
        )
        saved_state_snapshots: list[dict[str, object]] = []

        with (
            patch(
                'lib.orchestration.load_collection_state',
                return_value={'enumeration_checkpoint_store_time_max': None, 'files': {}},
            ),
            patch('lib.orchestration.fetch_collection_discovery', return_value=discovery_result) as mock_fetch,
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
            mock_save.side_effect = lambda storage_root, collection_id, state: saved_state_snapshots.append(deepcopy(state))
            mock_datetime.now.return_value = datetime(2026, 3, 7, 15, 0, 0, tzinfo=UTC)
            result = process_collection_job(
                client,
                collection_job,
                Path('/tmp/storage'),
                'https://example.org/wasapi',
                worksheet,
                header_location,
            )

        planning_state = deepcopy(saved_state_snapshots[1])
        saved_state = deepcopy(saved_state_snapshots[-1])
        self.assertEqual(
            planning_state['files']['ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz']['status'], 'pending_download'
        )
        self.assertEqual(
            planning_state['files']['ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz']['warc_path'],
            '/tmp/storage/collections/123/UNKNOWN_SEED/2026/03/ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz',
        )
        self.assertEqual(saved_state['enumeration_checkpoint_store_time_max'], '2026-03-06T12:00:00Z')
        self.assertIsNone(mock_fetch.call_args.kwargs['after_datetime'])
        status_updates = [call.args[3] for call in mock_update_status.call_args_list]
        self.assertEqual(status_updates[0].processing_status_main, STATUS_DISCOVERY_IN_PROGRESS)
        self.assertEqual(status_updates[0].processing_status_detail, 'full historical backfill')
        self.assertEqual(status_updates[0].status_last_fetch_file_count, '')
        self.assertEqual(status_updates[1].processing_status_main, STATUS_DOWNLOAD_PLANNING_COMPLETE)
        self.assertEqual(status_updates[1].processing_status_detail, 'download planning complete')
        self.assertEqual(status_updates[1].status_last_fetch_file_count, '1')
        self.assertEqual(status_updates[2].processing_status_main, STATUS_DOWNLOADING_IN_PROGRESS)
        self.assertEqual(status_updates[2].processing_status_detail, '0% (0/1 files)')
        self.assertEqual(status_updates[2].status_last_fetch_file_count, '1')
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
        self.assertEqual(result.status_update.processing_status_detail, '1 file download completed successfully')
        self.assertEqual(result.status_update.status_last_fetch_file_count, '1')
        self.assertEqual(result.summary_update.summary_status_downloaded_warcs_count, '0')
        self.assertEqual(result.summary_update.summary_status_downloaded_warcs_size, '0.0 GB')

    def test_zero_planned_downloads_write_planning_then_no_new_files_statuses(self) -> None:
        """
        Checks that zero planned downloads write planning-complete and no-new-files intermediate statuses.
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
        discovery_result.records = []
        discovery_result.request_records = [{'page': 1}]
        discovery_result.completed_successfully = True
        discovery_result.max_observed_store_time = '2026-03-06T12:00:00Z'

        with (
            patch(
                'lib.orchestration.load_collection_state',
                return_value={'enumeration_checkpoint_store_time_max': None, 'files': {}},
            ),
            patch('lib.orchestration.fetch_collection_discovery', return_value=discovery_result),
            patch('lib.orchestration.save_collection_state'),
            patch('lib.orchestration.log_planned_download_paths'),
            patch('lib.orchestration.log_collection_download_summary'),
            patch('lib.orchestration.update_collection_processing_status') as mock_update_status,
            patch('lib.orchestration.update_collection_final_reporting'),
            patch('lib.orchestration.datetime') as mock_datetime,
        ):
            mock_datetime.now.return_value = datetime(2026, 3, 7, 15, 0, 0, tzinfo=UTC)
            result = process_collection_job(
                client,
                collection_job,
                Path('/tmp/storage'),
                'https://example.org/wasapi',
                worksheet,
                header_location,
            )

        status_updates = [call.args[3] for call in mock_update_status.call_args_list]
        self.assertEqual(status_updates[0].processing_status_main, STATUS_DISCOVERY_IN_PROGRESS)
        self.assertEqual(status_updates[1].processing_status_main, STATUS_DOWNLOAD_PLANNING_COMPLETE)
        self.assertEqual(status_updates[1].processing_status_detail, 'download planning complete')
        self.assertEqual(status_updates[1].status_last_fetch_file_count, '0')
        self.assertEqual(status_updates[2].processing_status_main, STATUS_NO_NEW_FILES_TO_DOWNLOAD)
        self.assertEqual(status_updates[2].processing_status_detail, 'no new files to download')
        self.assertEqual(status_updates[2].status_last_fetch_file_count, '0')
        self.assertEqual(result.status_update.processing_status_main, STATUS_NO_NEW_FILES_TO_DOWNLOAD)
        self.assertEqual(
            result.status_update.processing_status_detail,
            f"since {format_local_display_timestamp('2026-03-07T15:00:00+00:00')}",
        )
        self.assertEqual(
            result.summary_update.summary_status_last_wasapi_check,
            format_local_display_timestamp('2026-03-07T15:00:00+00:00'),
        )
        self.assertEqual(result.summary_update.summary_status_downloaded_warcs_count, '0')
        self.assertEqual(result.summary_update.summary_status_downloaded_warcs_size, '0.0 GB')

    def test_planned_downloads_persisted_before_download_attempts(self) -> None:
        """
        Checks that planned downloads are persisted before the sequential download loop begins.
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
        download_result.destination_path = Path('/tmp/storage/collections/123/UNKNOWN_SEED/2026/03/file.warc.gz')
        fixity_result = FixityResult(
            success=True,
            warc_path=download_result.destination_path,
            sha256_path=Path('/tmp/storage/collections/123/UNKNOWN_SEED/2026/03/file.warc.gz.sha256'),
            json_path=Path('/tmp/storage/collections/123/UNKNOWN_SEED/2026/03/file.warc.gz.json'),
            sha256_hexdigest='abc123',
            size=11,
            source_url='https://example.org/alpha.warc.gz',
            completed_at='2026-03-06T12:34:56+00:00',
            error_message=None,
        )
        saved_state_snapshots: list[dict[str, object]] = []

        with (
            patch(
                'lib.orchestration.load_collection_state',
                return_value={'enumeration_checkpoint_store_time_max': None, 'files': {}},
            ),
            patch('lib.orchestration.fetch_collection_discovery', return_value=discovery_result),
            patch('lib.orchestration.save_collection_state') as mock_save,
            patch('lib.orchestration.build_planned_download_paths', return_value=['planned-path']),
            patch('lib.orchestration.log_planned_download_paths'),
            patch('lib.orchestration.download_to_path', return_value=download_result) as mock_download,
            patch('lib.orchestration.write_fixity_sidecars', return_value=fixity_result) as mock_fixity,
            patch('lib.orchestration.log_collection_download_summary') as mock_log_summary,
            patch('lib.orchestration.update_collection_processing_status'),
            patch('lib.orchestration.update_collection_final_reporting'),
            patch('lib.orchestration.datetime') as mock_datetime,
        ):
            mock_save.side_effect = lambda storage_root, collection_id, state: saved_state_snapshots.append(deepcopy(state))
            mock_datetime.now.return_value = datetime(2026, 3, 7, 15, 0, 0, tzinfo=UTC)
            process_collection_job(
                client,
                collection_job,
                Path('/tmp/storage'),
                'https://example.org/wasapi',
                worksheet,
                header_location,
            )

        self.assertEqual(len(saved_state_snapshots), 4)
        planning_state = deepcopy(saved_state_snapshots[1])
        self.assertEqual(
            planning_state['files']['ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz']['status'],
            'pending_download',
        )
        self.assertEqual(
            planning_state['files']['ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz']['warc_path'],
            '/tmp/storage/collections/123/UNKNOWN_SEED/2026/03/ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz',
        )
        self.assertEqual(
            planning_state['files']['ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz']['source_url'],
            'https://example.org/alpha.warc.gz',
        )
        self.assertEqual(
            planning_state['files']['ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz']['discovered_at'],
            '2026-03-07T15:00:00+00:00',
        )
        self.assertEqual(mock_download.call_count, 1)
        self.assertEqual(mock_fixity.call_count, 1)
        self.assertEqual(mock_log_summary.call_args.args[1], 1)
        self.assertEqual(mock_log_summary.call_args.args[2], 1)
        self.assertEqual(mock_log_summary.call_args.args[4], [fixity_result])

    def test_skips_checkpoint_save_when_discovery_not_complete(self) -> None:
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
        download_result.destination_path = Path('/tmp/storage/collections/123/UNKNOWN_SEED/2026/03/file.warc.gz')
        fixity_result = FixityResult(
            success=True,
            warc_path=download_result.destination_path,
            sha256_path=Path('/tmp/storage/collections/123/UNKNOWN_SEED/2026/03/file.warc.gz.sha256'),
            json_path=Path('/tmp/storage/collections/123/UNKNOWN_SEED/2026/03/file.warc.gz.json'),
            sha256_hexdigest='abc123',
            size=11,
            source_url='https://example.org/alpha.warc.gz',
            completed_at='2026-03-06T12:34:56+00:00',
            error_message=None,
        )
        saved_state_snapshots: list[dict[str, object]] = []

        with (
            patch(
                'lib.orchestration.load_collection_state',
                return_value={'enumeration_checkpoint_store_time_max': None, 'files': {}},
            ),
            patch('lib.orchestration.fetch_collection_discovery', return_value=discovery_result),
            patch('lib.orchestration.save_collection_state') as mock_save,
            patch('lib.orchestration.build_planned_download_paths', return_value=['planned-path']),
            patch('lib.orchestration.log_planned_download_paths'),
            patch('lib.orchestration.download_to_path', return_value=download_result) as mock_download,
            patch('lib.orchestration.write_fixity_sidecars', return_value=fixity_result),
            patch('lib.orchestration.log_collection_download_summary') as mock_log_summary,
            patch('lib.orchestration.update_collection_processing_status'),
            patch('lib.orchestration.update_collection_final_reporting'),
            patch('lib.orchestration.datetime') as mock_datetime,
        ):
            mock_save.side_effect = lambda storage_root, collection_id, state: saved_state_snapshots.append(deepcopy(state))
            mock_datetime.now.return_value = datetime(2026, 3, 7, 15, 0, 0, tzinfo=UTC)
            process_collection_job(
                client,
                collection_job,
                Path('/tmp/storage'),
                'https://example.org/wasapi',
                worksheet,
                header_location,
            )

        self.assertGreaterEqual(len(saved_state_snapshots), 2)
        self.assertEqual(saved_state_snapshots[0]['enumeration_checkpoint_store_time_max'], None)
        self.assertEqual(
            saved_state_snapshots[0]['files']['ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz']['status'],
            'pending_download',
        )
        self.assertEqual(
            saved_state_snapshots[0]['files']['ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz']['warc_path'],
            '/tmp/storage/collections/123/UNKNOWN_SEED/2026/03/ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz',
        )
        self.assertEqual(
            saved_state_snapshots[0]['files']['ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz']['source_url'],
            'https://example.org/alpha.warc.gz',
        )
        self.assertEqual(
            saved_state_snapshots[0]['files']['ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz']['discovered_at'],
            '2026-03-07T15:00:00+00:00',
        )
        self.assertEqual(mock_download.call_count, 1)
        self.assertEqual(mock_log_summary.call_args.args[3], [download_result])
        self.assertEqual(mock_log_summary.call_args.args[4], [fixity_result])

    def test_checkpointed_run_uses_overlap_window_boundary_for_discovery(self) -> None:
        """
        Checks that a checkpointed collection uses the overlap-window boundary.
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
        discovery_result.records = []
        discovery_result.request_records = [{'page': 1}]
        discovery_result.completed_successfully = True
        discovery_result.max_observed_store_time = '2026-03-06T12:00:00Z'

        with (
            patch(
                'lib.orchestration.load_collection_state',
                return_value={'enumeration_checkpoint_store_time_max': '2026-03-01T12:00:00Z', 'files': {}},
            ),
            patch('lib.orchestration.fetch_collection_discovery', return_value=discovery_result) as mock_fetch,
            patch('lib.orchestration.save_collection_state') as mock_save,
            patch('lib.orchestration.log_planned_download_paths'),
            patch('lib.orchestration.log_collection_download_summary'),
            patch('lib.orchestration.update_collection_processing_status') as mock_update_status,
            patch('lib.orchestration.update_collection_final_reporting'),
            patch('lib.orchestration.datetime') as mock_datetime,
        ):
            mock_datetime.now.return_value = datetime(2026, 3, 7, 15, 0, 0, tzinfo=UTC)
            process_collection_job(
                client,
                collection_job,
                Path('/tmp/storage'),
                'https://example.org/wasapi',
                worksheet,
                header_location,
            )

        self.assertEqual(
            mock_fetch.call_args.kwargs['after_datetime'],
            datetime(2026, 1, 30, 12, 0, 0, tzinfo=UTC),
        )
        status_updates = [call.args[3] for call in mock_update_status.call_args_list]
        self.assertEqual(
            status_updates[0].processing_status_detail,
            f"store-time-after {format_local_display_timestamp('2026-01-30T12:00:00+00:00')}",
        )
        self.assertEqual(mock_save.call_args.args[2]['enumeration_checkpoint_store_time_max'], '2026-03-06T12:00:00Z')

    def test_reconciliation_only_missing_file_flows_into_sequential_downloads(self) -> None:
        """
        Checks that a reconciliation-only missing file is passed into the existing sequential download flow.
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
        discovery_result.records = []
        discovery_result.request_records = [{'page': 1}]
        discovery_result.completed_successfully = True
        discovery_result.max_observed_store_time = '2026-03-06T12:00:00Z'
        download_result = MagicMock()
        download_result.success = True
        download_result.bytes_written = 11
        download_result.destination_path = Path('/tmp/storage/collections/123/UNKNOWN_SEED/2026/03/file.warc.gz')
        fixity_result = FixityResult(
            success=True,
            warc_path=download_result.destination_path,
            sha256_path=Path('/tmp/storage/collections/123/UNKNOWN_SEED/2026/03/file.warc.gz.sha256'),
            json_path=Path('/tmp/storage/collections/123/UNKNOWN_SEED/2026/03/file.warc.gz.json'),
            sha256_hexdigest='abc123',
            size=11,
            source_url='https://example.org/reconciliation-alpha.warc.gz',
            completed_at='2026-03-06T12:34:56+00:00',
            error_message=None,
        )
        loaded_state = {
            'enumeration_checkpoint_store_time_max': None,
            'files': {
                'ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz': {
                    'source_url': 'https://example.org/reconciliation-alpha.warc.gz',
                    'warc_path': '/tmp/storage/collections/123/UNKNOWN_SEED/2026/03/missing-alpha.warc.gz',
                    'status': 'failed',
                }
            },
        }

        with (
            patch('lib.orchestration.load_collection_state', return_value=loaded_state),
            patch('lib.orchestration.fetch_collection_discovery', return_value=discovery_result),
            patch('lib.orchestration.save_collection_state'),
            patch('lib.orchestration.build_planned_download_paths', return_value=[]),
            patch('lib.orchestration.log_planned_download_paths'),
            patch('lib.orchestration.download_to_path', return_value=download_result) as mock_download,
            patch('lib.orchestration.write_fixity_sidecars', return_value=fixity_result),
            patch('lib.orchestration.log_collection_download_summary') as mock_log_summary,
            patch('lib.orchestration.update_collection_processing_status'),
            patch('lib.orchestration.update_collection_final_reporting'),
            patch('lib.orchestration.datetime') as mock_datetime,
        ):
            mock_datetime.now.return_value = datetime(2026, 3, 7, 15, 0, 0, tzinfo=UTC)
            result = process_collection_job(
                client,
                collection_job,
                Path('/tmp/storage'),
                'https://example.org/wasapi',
                worksheet,
                header_location,
            )

        self.assertEqual(mock_download.call_count, 1)
        self.assertEqual(mock_download.call_args.args[1], 'https://example.org/reconciliation-alpha.warc.gz')
        self.assertEqual(mock_log_summary.call_args.args[2], 1)
        self.assertEqual(result.status_update.processing_status_main, STATUS_DOWNLOADED_WITHOUT_ERRORS)

    def test_persists_discovery_planned_files_before_download_attempts_begin(self) -> None:
        """
        Checks that planned downloads are written to local state before the downloader is invoked.
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
        download_result.destination_path = Path('/tmp/storage/collections/123/UNKNOWN_SEED/2026/03/file.warc.gz')
        download_result.error_message = '502 Bad Gateway'
        saved_state_snapshots: list[dict[str, object]] = []

        with (
            patch(
                'lib.orchestration.load_collection_state',
                return_value={'enumeration_checkpoint_store_time_max': None, 'files': {}},
            ),
            patch('lib.orchestration.fetch_collection_discovery', return_value=discovery_result),
            patch('lib.orchestration.save_collection_state') as mock_save,
            patch('lib.orchestration.build_planned_download_paths', return_value=['planned-path']),
            patch('lib.orchestration.log_planned_download_paths'),
            patch('lib.orchestration.download_to_path', return_value=download_result) as mock_download,
            patch('lib.orchestration.write_fixity_sidecars'),
            patch('lib.orchestration.log_collection_download_summary'),
            patch('lib.orchestration.update_collection_processing_status'),
            patch('lib.orchestration.update_collection_final_reporting'),
            patch('lib.orchestration.datetime') as mock_datetime,
        ):
            mock_save.side_effect = lambda storage_root, collection_id, state: saved_state_snapshots.append(deepcopy(state))
            mock_datetime.now.return_value = datetime(2026, 3, 7, 15, 0, 0, tzinfo=UTC)
            process_collection_job(
                client,
                collection_job,
                Path('/tmp/storage'),
                'https://example.org/wasapi',
                worksheet,
                header_location,
            )

        planning_state = saved_state_snapshots[1]
        saved_manifest_entry = planning_state['files']['ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz']
        self.assertEqual(saved_manifest_entry['status'], 'pending_download')
        self.assertEqual(saved_manifest_entry['source_url'], 'https://example.org/alpha.warc.gz')
        self.assertEqual(
            saved_manifest_entry['warc_path'],
            '/tmp/storage/collections/123/UNKNOWN_SEED/2026/03/ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz',
        )
        self.assertEqual(saved_manifest_entry['discovered_at'], '2026-03-07T15:00:00+00:00')
        self.assertEqual(mock_download.call_count, 1)


class TestRunPlannedDownloads(TestCase):
    """
    Test cases for the sequential planned-download loop.
    """

    def test_download_progress_helper_formats_expected_update_text(self) -> None:
        """
        Checks that progress-detail text uses the expected compact update format.
        """
        result = build_download_progress_detail(40, 6, 15)

        self.assertEqual(result, '40% (6/15 files)')

    def test_download_progress_helper_emits_every_ten_completed_downloads(self) -> None:
        """
        Checks that progress updates are emitted only when another ten downloads complete.
        """
        last_reported_completed_count, progress_detail = get_download_progress_file_interval_update(25, 9, 0)
        self.assertEqual(last_reported_completed_count, 0)
        self.assertIsNone(progress_detail)

        last_reported_completed_count, progress_detail = get_download_progress_file_interval_update(
            25,
            10,
            last_reported_completed_count,
        )
        self.assertEqual(last_reported_completed_count, 10)
        self.assertEqual(progress_detail, '40% (10/25 files)')

        last_reported_completed_count, progress_detail = get_download_progress_file_interval_update(
            25,
            11,
            last_reported_completed_count,
        )
        self.assertEqual(last_reported_completed_count, 10)
        self.assertIsNone(progress_detail)

        last_reported_completed_count, progress_detail = get_download_progress_file_interval_update(
            25,
            20,
            last_reported_completed_count,
        )
        self.assertEqual(last_reported_completed_count, 20)
        self.assertEqual(progress_detail, '80% (20/25 files)')

    def test_logs_debug_message_immediately_before_download_attempt(self) -> None:
        """
        Checks that a debug log entry is emitted before a planned download begins.
        """
        planned_download = PlannedDownload(
            filename='ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz',
            source_url='https://example.org/alpha.warc.gz',
            planned_paths=build_planned_download_paths(
                Path('/tmp/storage'),
                123,
                [{'filename': 'ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz'}],
            )[0],
        )
        state = {'files': {}}
        client = MagicMock(spec=httpx.Client)
        download_result = MagicMock()
        download_result.success = False
        download_result.error_message = '502 Bad Gateway'

        with (
            patch('lib.orchestration.download_to_path', return_value=download_result),
            patch('lib.orchestration.save_collection_state'),
            patch('lib.orchestration.log.debug') as mock_log_debug,
            patch('pathlib.Path.exists', return_value=False),
        ):
            run_planned_downloads(
                client=client,
                storage_root=Path('/tmp/storage'),
                collection_id=123,
                state=state,
                planned_downloads=[planned_download],
            )

        self.assertTrue(mock_log_debug.called)
        self.assertEqual(
            mock_log_debug.call_args.args,
            (
                'Collection ``%s`` about to download ``%s`` from ``%s`` to ``%s``',
                123,
                'ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz',
                'https://example.org/alpha.warc.gz',
                Path('/tmp/storage/collections/123/UNKNOWN_SEED/2026/03/ARCHIVEIT-123-20260306123456-00000-alpha.warc.gz'),
            ),
        )

    def test_progress_callback_emits_every_ten_completed_downloads(self) -> None:
        """
        Checks that the sequential download loop emits progress after every ten completed downloads.
        """
        planned_downloads = [
            PlannedDownload(
                filename=f'ARCHIVEIT-123-202603061234{index:02d}-0000{index}-alpha.warc.gz',
                source_url=f'https://example.org/{index}.warc.gz',
                planned_paths=build_planned_download_paths(
                    Path('/tmp/storage'),
                    123,
                    [{'filename': f'ARCHIVEIT-123-202603061234{index:02d}-0000{index}-alpha.warc.gz'}],
                )[0],
            )
            for index in range(25)
        ]
        state = {'files': {}}
        client = MagicMock(spec=httpx.Client)
        download_result = MagicMock()
        download_result.success = False
        download_result.error_message = '502 Bad Gateway'
        progress_updates: list[str] = []

        with (
            patch('lib.orchestration.download_to_path', return_value=download_result),
            patch('lib.orchestration.save_collection_state'),
            patch('pathlib.Path.exists', return_value=False),
        ):
            run_planned_downloads(
                client=client,
                storage_root=Path('/tmp/storage'),
                collection_id=123,
                state=state,
                planned_downloads=planned_downloads,
                progress_callback=progress_updates.append,
            )

        self.assertEqual(
            progress_updates,
            [
                '40% (10/25 files)',
                '80% (20/25 files)',
            ],
        )


class TestCollectionReportingHelpers(TestCase):
    """
    Test cases for final spreadsheet reporting helper payloads.
    """

    def test_build_collection_final_report_uses_on_disk_collection_totals(self) -> None:
        """
        Checks that final summary fields report cumulative on-disk totals, not only current-run successes.
        """
        collection_job = CollectionJob(123, 'UA', 'https://example.com', 'Example', 7)
        successful_download = MagicMock()
        successful_download.success = True
        successful_download.bytes_written = 11

        with patch(
            'lib.orchestration.get_collection_downloaded_totals',
            return_value=(3, 3 * (1024**3)),
        ):
            result = build_collection_final_report(
                storage_root=Path('/tmp/storage'),
                collection_job=collection_job,
                discovery_completed_at='2026-03-07T15:00:00+00:00',
                planned_downloads=[MagicMock()],
                download_results=[successful_download],
                fixity_results=[],
            )

        self.assertEqual(result.status_update.processing_status_main, STATUS_DOWNLOADED_WITHOUT_ERRORS)
        self.assertEqual(
            result.summary_update.summary_status_last_wasapi_check,
            format_local_display_timestamp('2026-03-07T15:00:00+00:00'),
        )
        self.assertEqual(result.summary_update.summary_status_downloaded_warcs_count, '3')
        self.assertEqual(result.summary_update.summary_status_downloaded_warcs_size, '3.0 GB')

    def test_build_collection_final_report_no_new_downloads_still_reports_on_disk_totals(self) -> None:
        """
        Checks that no-op collections still report existing downloaded totals from disk.
        """
        collection_job = CollectionJob(123, 'UA', 'https://example.com', 'Example', 7)

        with patch(
            'lib.orchestration.get_collection_downloaded_totals',
            return_value=(2, 2 * (1024**3)),
        ):
            result = build_collection_final_report(
                storage_root=Path('/tmp/storage'),
                collection_job=collection_job,
                discovery_completed_at='2026-03-07T15:00:00+00:00',
                planned_downloads=[],
                download_results=[],
                fixity_results=[],
            )

        self.assertEqual(result.status_update.processing_status_main, STATUS_NO_NEW_FILES_TO_DOWNLOAD)
        self.assertEqual(
            result.status_update.processing_status_detail,
            f"since {format_local_display_timestamp('2026-03-07T15:00:00+00:00')}",
        )
        self.assertEqual(
            result.summary_update.summary_status_last_wasapi_check,
            format_local_display_timestamp('2026-03-07T15:00:00+00:00'),
        )
        self.assertEqual(result.summary_update.summary_status_downloaded_warcs_count, '2')
        self.assertEqual(result.summary_update.summary_status_downloaded_warcs_size, '2.0 GB')

    def test_build_collection_final_report_for_file_failures(self) -> None:
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
        self.assertEqual(result.status_update.processing_status_detail, '1 file operation failed')
        self.assertEqual(
            result.summary_update.summary_status_last_wasapi_check,
            format_local_display_timestamp('2026-03-07T15:00:00+00:00'),
        )
        self.assertEqual(result.summary_update.summary_status_downloaded_warcs_size, '0.0 GB')

    def test_build_collection_failure_report_for_discovery_failure(self) -> None:
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
        self.assertEqual(result.status_update.status_last_fetch_file_count, '0')
        self.assertEqual(
            result.summary_update.summary_status_last_wasapi_check,
            format_local_display_timestamp('2026-03-07T15:00:00+00:00'),
        )
        self.assertEqual(result.summary_update.summary_status_server_path, '/tmp/storage/collections/123')


if __name__ == '__main__':
    unittest.main()
