import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

sys.path.append(str(Path(__file__).parent.parent))

from lib.local_state import (
    LocalStateError,
    build_collection_root_path,
    build_state_file_path,
    load_collection_state,
    make_default_collection_state,
    save_collection_state,
    update_file_manifest_for_planned_download,
)


class TestLocalStatePaths(TestCase):
    """
    Test cases for local state path helpers.
    """

    def test_builds_collection_root_and_state_file_paths(self):
        """
        Checks that collection paths match the v05 storage layout.
        """
        storage_root = Path('/tmp/warc-storage')

        collection_root = build_collection_root_path(storage_root, 123)
        state_file_path = build_state_file_path(storage_root, 123)

        self.assertEqual(collection_root, storage_root / 'collections' / '123')
        self.assertEqual(state_file_path, storage_root / 'collections' / '123' / 'state.json')


class TestLoadCollectionState(TestCase):
    """
    Test cases for loading collection state.
    """

    def test_returns_default_state_when_file_is_missing(self):
        """
        Checks that missing state files return the default state.
        """
        with TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)

            result = load_collection_state(storage_root, 123)

            self.assertEqual(result, make_default_collection_state())

    def test_load_fills_missing_required_keys(self):
        """
        Checks that missing top-level keys are filled from defaults.
        """
        with TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            state_file_path = build_state_file_path(storage_root, 123)
            state_file_path.parent.mkdir(parents=True, exist_ok=True)
            state_file_path.write_text(json.dumps({'files': {'alpha.warc.gz': {'status': 'downloaded'}}}), encoding='utf-8')

            result = load_collection_state(storage_root, 123)

            self.assertEqual(result['enumeration_checkpoint_store_time_max'], None)
            self.assertEqual(result['files'], {'alpha.warc.gz': {'status': 'downloaded'}})

    def test_raises_for_malformed_json(self):
        """
        Checks that malformed JSON raises a clear local-state error.
        """
        with TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            state_file_path = build_state_file_path(storage_root, 123)
            state_file_path.parent.mkdir(parents=True, exist_ok=True)
            state_file_path.write_text('{not valid json', encoding='utf-8')

            with self.assertRaises(LocalStateError):
                load_collection_state(storage_root, 123)

    def test_raises_when_top_level_json_is_not_an_object(self):
        """
        Checks that non-object JSON payloads raise a clear local-state error.
        """
        with TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            state_file_path = build_state_file_path(storage_root, 123)
            state_file_path.parent.mkdir(parents=True, exist_ok=True)
            state_file_path.write_text(json.dumps(['not', 'an', 'object']), encoding='utf-8')

            with self.assertRaises(LocalStateError):
                load_collection_state(storage_root, 123)


class TestSaveCollectionState(TestCase):
    """
    Test cases for saving collection state.
    """

    def test_save_and_load_round_trip(self):
        """
        Checks that a saved state can be loaded back successfully.
        """
        with TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            state = {
                'enumeration_checkpoint_store_time_max': '2026-03-06T12:00:00Z',
                'files': {
                    'alpha.warc.gz': {
                        'status': 'failed',
                        'last_attempt_at': '2026-03-06T12:01:00Z',
                        'error_count': 2,
                        'error_summary': 'timeout',
                    },
                },
            }

            save_collection_state(storage_root, 123, state)
            result = load_collection_state(storage_root, 123)

            self.assertEqual(result, state)

    def test_save_creates_final_state_file_without_leftover_temp_files(self):
        """
        Checks that save leaves a final state.json and no leftover temp file.
        """
        with TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            state = make_default_collection_state()

            state_file_path = save_collection_state(storage_root, 123, state)

            self.assertTrue(state_file_path.exists())
            self.assertEqual(state_file_path.name, 'state.json')
            sibling_names = {path.name for path in state_file_path.parent.iterdir()}
            self.assertEqual(sibling_names, {'state.json'})


class TestPlannedDownloadManifestUpdates(TestCase):
    """
    Test cases for pre-download manifest persistence.
    """

    def test_records_pending_download_metadata_for_new_entry(self):
        """
        Checks that planned download metadata is persisted before any download attempt occurs.
        """
        state = make_default_collection_state()

        result = update_file_manifest_for_planned_download(
            state=state,
            filename='alpha.warc.gz',
            source_url='https://example.org/alpha.warc.gz',
            warc_path=Path('/tmp/storage/collections/123/warcs/2026/03/alpha.warc.gz'),
            discovered_at='2026-03-07T15:00:00+00:00',
        )

        self.assertEqual(result['status'], 'pending_download')
        self.assertEqual(result['source_url'], 'https://example.org/alpha.warc.gz')
        self.assertEqual(result['warc_path'], '/tmp/storage/collections/123/warcs/2026/03/alpha.warc.gz')
        self.assertEqual(result['discovered_at'], '2026-03-07T15:00:00+00:00')

    def test_preserves_downloaded_status_when_refreshing_planned_metadata(self):
        """
        Checks that already-downloaded entries keep their downloaded status when planning metadata is refreshed.
        """
        state = {
            'enumeration_checkpoint_store_time_max': None,
            'files': {
                'alpha.warc.gz': {
                    'status': 'downloaded',
                    'source_url': 'https://example.org/older-alpha.warc.gz',
                }
            },
        }

        result = update_file_manifest_for_planned_download(
            state=state,
            filename='alpha.warc.gz',
            source_url='https://example.org/alpha.warc.gz',
            warc_path=Path('/tmp/storage/collections/123/warcs/2026/03/alpha.warc.gz'),
            discovered_at='2026-03-07T15:00:00+00:00',
        )

        self.assertEqual(result['status'], 'downloaded')
        self.assertEqual(result['source_url'], 'https://example.org/alpha.warc.gz')
        self.assertEqual(result['warc_path'], '/tmp/storage/collections/123/warcs/2026/03/alpha.warc.gz')
        self.assertEqual(result['discovered_at'], '2026-03-07T15:00:00+00:00')


if __name__ == '__main__':
    unittest.main()
