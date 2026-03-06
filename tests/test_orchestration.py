import os
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

import httpx

sys.path.append(str(Path(__file__).parent.parent))

from lib.collection_sheet import CollectionJob
from lib.orchestration import (
    count_pending_download_candidates,
    get_archive_it_credentials,
    get_downloaded_storage_root,
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
        discovery_result = MagicMock()
        discovery_result.records = [{'filename': 'alpha.warc.gz'}]
        discovery_result.request_records = [{'page': 1}]
        discovery_result.completed_successfully = True
        discovery_result.max_observed_store_time = '2026-03-06T12:00:00Z'

        with (
            patch(
                'lib.orchestration.load_collection_state',
                return_value={'enumeration_checkpoint_store_time_max': None, 'files': {}},
            ),
            patch('lib.orchestration.compute_store_time_after_datetime') as mock_compute,
            patch('lib.orchestration.fetch_collection_discovery', return_value=discovery_result),
            patch('lib.orchestration.save_collection_state') as mock_save,
            patch('lib.orchestration.log_not_yet_implemented_stages') as mock_log_stub,
        ):
            mock_compute.return_value = datetime(2026, 2, 1, 0, 0, 0, tzinfo=UTC)
            process_collection_job(client, collection_job, Path('/tmp/storage'), 'https://example.org/wasapi')

        saved_state = mock_save.call_args.args[2]
        self.assertEqual(saved_state['enumeration_checkpoint_store_time_max'], '2026-03-06T12:00:00Z')
        self.assertEqual(mock_log_stub.call_args.args[1], 1)

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
        discovery_result = MagicMock()
        discovery_result.records = [{'filename': 'alpha.warc.gz'}]
        discovery_result.request_records = [{'page': 1}]
        discovery_result.completed_successfully = False
        discovery_result.max_observed_store_time = '2026-03-06T12:00:00Z'

        with (
            patch(
                'lib.orchestration.load_collection_state',
                return_value={'enumeration_checkpoint_store_time_max': None, 'files': {}},
            ),
            patch('lib.orchestration.compute_store_time_after_datetime') as mock_compute,
            patch('lib.orchestration.fetch_collection_discovery', return_value=discovery_result),
            patch('lib.orchestration.save_collection_state') as mock_save,
            patch('lib.orchestration.log_not_yet_implemented_stages') as mock_log_stub,
        ):
            mock_compute.return_value = datetime(2026, 2, 1, 0, 0, 0, tzinfo=UTC)
            process_collection_job(client, collection_job, Path('/tmp/storage'), 'https://example.org/wasapi')

        self.assertFalse(mock_save.called)
        self.assertEqual(mock_log_stub.call_args.args[1], 1)


if __name__ == '__main__':
    unittest.main()
