import sys
import unittest
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).parent.parent))

from lib.collection_sheet import (
    CollectionProcessingStatusUpdate,
    CollectionSheetContractError,
    CollectionSummaryUpdate,
    HeaderLocation,
    build_spreadsheet_editability_probe_update,
    load_collection_sheet_context,
    parse_collection_id,
    parse_collection_jobs,
    update_collection_final_reporting,
    update_collection_processing_status,
    validate_collection_sheet_connection,
    validate_required_reporting_fields,
)


class TestParseCollectionId(TestCase):
    """
    Test cases for parsing collection ids.
    """

    def test_integer_string(self) -> None:
        """
        Checks that a simple integer string parses successfully.
        """
        result = parse_collection_id('123')
        self.assertEqual(result, 123)

    def test_float_string(self) -> None:
        """
        Checks that a float-like string parses to an integer.
        """
        result = parse_collection_id('456.0')
        self.assertEqual(result, 456)

    def test_invalid_string(self) -> None:
        """
        Checks that invalid strings return None.
        """
        result = parse_collection_id('abc')
        self.assertIsNone(result)


class TestParseCollectionJobs(TestCase):
    """
    Test cases for parsing collection jobs.
    """

    def test_parses_active_rows(self) -> None:
        """
        Checks that only active rows become collection jobs.
        """
        values = [
            ['Notes above header'],
            ['Collection ID', 'Repository', 'Collection URL', 'Collection name', 'Collection-Status'],
            ['123', 'UA', 'https://example.com/1', 'Example One', 'Active'],
            ['456', 'MS', 'https://example.com/2', 'Example Two', 'Inactive'],
        ]
        result = parse_collection_jobs(values)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].collection_id, 123)
        self.assertEqual(result[0].repository, 'UA')
        self.assertEqual(result[0].row_number, 3)

    def test_old_active_inactive_header_is_not_accepted(self) -> None:
        """
        Checks that the old active/inactive header no longer satisfies the sheet contract.
        """
        values = [
            ['Header row follows'],
            ['Collection ID', 'Repository', 'Active/Inactive'],
            ['789', 'UA', 'Active'],
        ]
        result = parse_collection_jobs(values)
        self.assertEqual(result, [])

    def test_collection_status_header_is_accepted(self) -> None:
        """
        Checks that the production collection status header is accepted.
        """
        values = [
            ['Notes above header'],
            ['Collection ID', 'Repository', 'Collection-Status'],
            ['321', 'UA', 'Active'],
        ]
        result = parse_collection_jobs(values)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].collection_id, 321)
        self.assertEqual(result[0].repository, 'UA')

    def test_new_reporting_column_labels_are_accepted(self) -> None:
        """
        Checks that the new row-3 reporting column labels are accepted.
        """
        worksheet = MagicMock()
        worksheet.get_all_values.return_value = [
            ['Notes above header'],
            ['More notes'],
            [
                'Collection ID',
                'Collection-Status',
                'Seed Count',
                'status-last-fetch',
                'status-detail',
                'status-last-fetch-file-count',
                'last-download-timestamp',
                'total-col-WARC-count',
                'total-downloaded-collection-size',
                'server-file-path-collectionLevel',
            ],
            ['123', 'Active', '', '', '', '', '', '', '', ''],
        ]
        client = MagicMock()
        spreadsheet = MagicMock()
        spreadsheet.worksheet.return_value = worksheet
        client.open_by_key.return_value = spreadsheet

        with patch('lib.collection_sheet.get_gspread_client', return_value=client):
            result = load_collection_sheet_context('spreadsheet-id')

        self.assertEqual(result.header_location.header_row_index, 2)
        self.assertEqual(result.header_location.column_map['seed_count'], 2)
        self.assertEqual(result.header_location.column_map['status_last_fetch'], 3)
        self.assertEqual(result.header_location.column_map['status_detail'], 4)
        self.assertEqual(result.header_location.column_map['status_last_fetch_file_count'], 5)
        self.assertEqual(result.header_location.column_map['last_download_timestamp'], 6)
        self.assertEqual(result.header_location.column_map['total_col_warc_count'], 7)
        self.assertEqual(result.header_location.column_map['total_downloaded_collection_size'], 8)
        self.assertEqual(result.header_location.column_map['server_file_path_collection_level'], 9)


class TestCollectionReportingContract(TestCase):
    """
    Test cases for worksheet reporting-column validation and writes.
    """

    def test_validation_fails_when_reporting_column_is_missing(self) -> None:
        """
        Checks that reporting validation fails clearly when a required column is absent.
        """
        header_location = HeaderLocation(
            header_row_index=1,
            column_map={
                'collection_id': 0,
                'collection_status': 1,
                'status_last_fetch': 2,
                'status_last_fetch_file_count': 3,
                'last_download_timestamp': 4,
                'total_col_warc_count': 5,
                'total_downloaded_collection_size': 6,
                'server_file_path_collection_level': 7,
            },
        )

        with self.assertRaises(CollectionSheetContractError) as exc_context:
            validate_required_reporting_fields(header_location)

        self.assertIn('status_detail', str(exc_context.exception))

    def test_start_status_write_uses_expected_row_and_payload(self) -> None:
        """
        Checks that start-status writes target the expected row and status columns.
        """
        worksheet = MagicMock()
        header_location = HeaderLocation(
            header_row_index=1,
            column_map={
                'status_last_fetch': 4,
                'status_detail': 5,
                'status_last_fetch_file_count': 6,
            },
        )
        status_update = CollectionProcessingStatusUpdate(
            status_last_fetch='discovery-in-progress',
            status_detail='full historical backfill',
            status_last_fetch_file_count='12',
        )

        update_collection_processing_status(worksheet, header_location, 7, status_update)

        self.assertEqual(
            worksheet.batch_update.call_args.args[0],
            [
                {'range': 'E7', 'values': [['discovery-in-progress']]},
                {'range': 'F7', 'values': [['full historical backfill']]},
                {'range': 'G7', 'values': [['12']]},
            ],
        )

    def test_final_reporting_write_includes_status_and_summary_fields(self) -> None:
        """
        Checks that final reporting writes status and required summary fields together.
        """
        worksheet = MagicMock()
        header_location = HeaderLocation(
            header_row_index=1,
            column_map={
                'status_last_fetch': 0,
                'status_detail': 1,
                'status_last_fetch_file_count': 2,
                'last_download_timestamp': 3,
                'total_col_warc_count': 4,
                'total_downloaded_collection_size': 5,
                'server_file_path_collection_level': 6,
                'seed_count': 7,
            },
        )
        status_update = CollectionProcessingStatusUpdate(
            status_last_fetch='downloaded-without-errors',
            status_detail='1 file download completed successfully',
            status_last_fetch_file_count='1',
        )
        summary_update = CollectionSummaryUpdate(
            last_download_timestamp='2026-03-07T15:00:00+00:00',
            total_col_warc_count='1',
            total_downloaded_collection_size='0.0 GB',
            server_file_path_collection_level='/tmp/storage/collections/123',
            seed_count='1',
        )

        update_collection_final_reporting(worksheet, header_location, 9, status_update, summary_update)

        self.assertEqual(
            worksheet.batch_update.call_args.args[0],
            [
                {'range': 'A9', 'values': [['downloaded-without-errors']]},
                {'range': 'B9', 'values': [['1 file download completed successfully']]},
                {'range': 'C9', 'values': [['1']]},
                {'range': 'D9', 'values': [['2026-03-07T15:00:00+00:00']]},
                {'range': 'E9', 'values': [['1']]},
                {'range': 'F9', 'values': [['0.0 GB']]},
                {'range': 'G9', 'values': [['/tmp/storage/collections/123']]},
                {'range': 'H9', 'values': [['1']]},
            ],
        )


class TestCollectionSheetConnectionValidation(TestCase):
    """
    Test cases for spreadsheet connection and editability validation.
    """

    def test_build_spreadsheet_editability_probe_update_targets_reporting_header(self) -> None:
        """
        Checks that the editability probe rewrites the status header cell with its existing value.
        """
        values = [
            ['Notes above header'],
            ['Collection ID', 'Collection-Status', 'Status-Main'],
            ['123', 'Active', ''],
        ]
        header_location = HeaderLocation(
            header_row_index=1,
            column_map={
                'collection_id': 0,
                'collection_status': 1,
                'processing_status_main': 2,
            },
        )

        result = build_spreadsheet_editability_probe_update(values, header_location)

        self.assertEqual(result, [{'range': 'C2', 'values': [['Status-Main']]}])

    def test_validate_collection_sheet_connection_loads_context_and_writes_probe(self) -> None:
        """
        Checks that connection validation opens the worksheet and performs a same-value editability write.
        """
        worksheet = MagicMock()
        worksheet.get_all_values.return_value = [
            ['Notes above header'],
            [
                'Collection ID',
                'Collection-Status',
                'Seed Count',
                'status-last-fetch',
                'status-detail',
                'status-last-fetch-file-count',
                'last-download-timestamp',
                'total-col-WARC-count',
                'total-downloaded-collection-size',
                'server-file-path-collectionLevel',
            ],
            ['123', 'Active', '', '', '', '', '', '', '', ''],
        ]
        client = MagicMock()
        spreadsheet = MagicMock()
        spreadsheet.worksheet.return_value = worksheet
        client.open_by_key.return_value = spreadsheet

        with patch('lib.collection_sheet.get_gspread_client', return_value=client):
            result = validate_collection_sheet_connection('spreadsheet-id')

        self.assertEqual(result.collection_jobs[0].collection_id, 123)
        self.assertEqual(worksheet.batch_update.call_args.args[0], [{'range': 'D2', 'values': [['status-last-fetch']]}])


if __name__ == '__main__':
    unittest.main()
