import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).parent.parent))

from lib.collection_sheet import CollectionJob, HeaderLocation


class TestGetRequiredLogFilePath(TestCase):
    """
    Test cases for log-path configuration.
    """

    def test_returns_log_file_under_configured_directory(self) -> None:
        """
        Checks that LOG_PATH is used to build the final log file path.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_file_path = Path(tmp_dir) / 'warc_tracker_script.log'
            with (
                patch.dict(os.environ, {'LOG_PATH': str(log_file_path)}, clear=False),
                patch('dotenv.load_dotenv', return_value=False),
            ):
                import main

                importlib.reload(main)
                result = main.LOG_FILE_PATH

            self.assertEqual(result, log_file_path)

    def test_raises_when_log_path_is_missing(self) -> None:
        """
        Checks that missing LOG_PATH raises a clear error.
        """
        with (
            patch.dict(os.environ, {}, clear=True),
            patch('dotenv.load_dotenv', return_value=False),
        ):
            with self.assertRaises(KeyError):
                import main

                importlib.reload(main)
                _ = main.LOG_FILE_PATH


class TestRunCollectionOrchestration(TestCase):
    """
    Test cases for the top-level collection orchestration manager.
    """

    def test_dev_collections_limits_processing_to_matching_collection_jobs(self) -> None:
        """
        Checks that DEV_COLLECTIONS filters processing while preserving the selected CollectionJob metadata.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_file_path = Path(tmp_dir) / 'warc_tracker_script.log'
            active_collection_jobs = [
                CollectionJob(22900, 'MS', 'https://example.com/22900', 'Alpha', 4),
                CollectionJob(15887, 'UA', 'https://example.com/15887', 'Beta', 7),
            ]
            sheet_context = SimpleNamespace(
                collection_jobs=active_collection_jobs,
                worksheet=MagicMock(),
                header_location=HeaderLocation(header_row_index=2, column_map={'status_last_fetch': 3}),
                values=[],
            )
            http_client = MagicMock()
            http_client_context = MagicMock()
            http_client_context.__enter__.return_value = http_client

            with (
                patch.dict(
                    os.environ,
                    {
                        'LOG_PATH': str(log_file_path),
                        'DEV_COLLECTIONS': '15887',
                    },
                    clear=False,
                ),
                patch('dotenv.load_dotenv', return_value=False),
            ):
                import main

                importlib.reload(main)
                with (
                    patch('main.load_collection_sheet_context', return_value=sheet_context),
                    patch('main.enforce_startup_run_coordination'),
                    patch('main.httpx.Client', return_value=http_client_context),
                    patch('main.process_collection_job') as mock_process_collection_job,
                ):
                    main.run_collection_orchestration(
                        spreadsheet_id='spreadsheet-id',
                        downloaded_storage_root=Path(tmp_dir),
                        wasapi_base_url='https://example.com/wasapi',
                        archive_it_credentials=('user', 'pass'),
                    )

                processed_collection_job = mock_process_collection_job.call_args.args[1]
                processed_count = mock_process_collection_job.call_count

        self.assertEqual(processed_collection_job, active_collection_jobs[1])
        self.assertEqual(processed_collection_job.row_number, 7)
        self.assertEqual(processed_count, 1)


if __name__ == '__main__':
    unittest.main()
