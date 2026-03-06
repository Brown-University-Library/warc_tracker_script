import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.append(str(Path(__file__).parent.parent))


class TestGetRequiredLogFilePath(TestCase):
    """
    Test cases for log-path configuration.
    """

    def test_returns_log_file_under_configured_directory(self):
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

    def test_raises_when_log_path_is_missing(self):
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


if __name__ == '__main__':
    unittest.main()
