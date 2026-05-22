import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).parent.parent))

from validate_spreadsheet_connection import (
    format_success_message,
    resolve_spreadsheet_id,
    run_validation,
)


class TestResolveSpreadsheetId(TestCase):
    """
    Test cases for resolving the spreadsheet id.
    """

    def test_uses_cli_value_when_present(self):
        """
        Checks that a CLI spreadsheet id takes precedence.
        """
        with patch.dict(os.environ, {'GSHEET_SPREADSHEET_ID': 'env-id'}, clear=True):
            result = resolve_spreadsheet_id(' cli-id ')

        self.assertEqual(result, 'cli-id')

    def test_uses_environment_value_when_cli_value_is_missing(self):
        """
        Checks that the environment supplies the default spreadsheet id.
        """
        with patch.dict(os.environ, {'GSHEET_SPREADSHEET_ID': 'env-id'}, clear=True):
            result = resolve_spreadsheet_id(None)

        self.assertEqual(result, 'env-id')

    def test_raises_when_no_spreadsheet_id_is_available(self):
        """
        Checks that missing spreadsheet ids fail clearly.
        """
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                resolve_spreadsheet_id(None)


class TestRunValidation(TestCase):
    """
    Test cases for the standalone spreadsheet validation runner.
    """

    def test_format_success_message_includes_worksheet_and_active_count(self):
        """
        Checks that success output includes the worksheet title and active collection count.
        """
        worksheet = SimpleNamespace(title='At Collection Level')
        sheet_context = SimpleNamespace(worksheet=worksheet, collection_jobs=[MagicMock(), MagicMock()])

        result = format_success_message(sheet_context)

        self.assertIn('At Collection Level', result)
        self.assertIn('2 active collection jobs', result)

    def test_run_validation_returns_zero_after_successful_validation(self):
        """
        Checks that successful validation exits cleanly.
        """
        worksheet = SimpleNamespace(title='At Collection Level')
        sheet_context = SimpleNamespace(worksheet=worksheet, collection_jobs=[])

        with (
            patch('validate_spreadsheet_connection.validate_collection_sheet_connection', return_value=sheet_context),
            patch('builtins.print') as mock_print,
        ):
            result = run_validation('spreadsheet-id')

        self.assertEqual(result, 0)
        self.assertIn('Spreadsheet connection validated', mock_print.call_args.args[0])

    def test_run_validation_returns_one_after_failed_validation(self):
        """
        Checks that failed validation returns a non-zero exit code.
        """
        with (
            patch(
                'validate_spreadsheet_connection.validate_collection_sheet_connection',
                side_effect=RuntimeError('nope'),
            ),
            patch('builtins.print') as mock_print,
        ):
            result = run_validation('spreadsheet-id')

        self.assertEqual(result, 1)
        self.assertIn('Spreadsheet connection validation failed', mock_print.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
