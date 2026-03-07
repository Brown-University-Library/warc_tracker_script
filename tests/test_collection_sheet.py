import sys
import unittest
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).parent.parent))

from lib.collection_sheet import (
    CollectionProcessingStatusUpdate,
    CollectionSheetContractError,
    CollectionSummaryUpdate,
    HeaderLocation,
    parse_collection_id,
    parse_collection_jobs,
    update_collection_final_reporting,
    update_collection_processing_status,
    validate_required_reporting_fields,
)


class TestParseCollectionId(TestCase):
    """
    Test cases for parsing collection ids.
    """

    def test_integer_string(self):
        """
        Checks that a simple integer string parses successfully.
        """
        result = parse_collection_id('123')
        self.assertEqual(result, 123)

    def test_float_string(self):
        """
        Checks that a float-like string parses to an integer.
        """
        result = parse_collection_id('456.0')
        self.assertEqual(result, 456)

    def test_invalid_string(self):
        """
        Checks that invalid strings return None.
        """
        result = parse_collection_id('abc')
        self.assertIsNone(result)


class TestParseCollectionJobs(TestCase):
    """
    Test cases for parsing collection jobs.
    """

    def test_parses_active_rows(self):
        """
        Checks that only active rows become collection jobs.
        """
        values = [
            ['Notes above header'],
            ['Collection ID', 'Repository', 'Collection URL', 'Collection name', 'Active/Inactive'],
            ['123', 'UA', 'https://example.com/1', 'Example One', 'Active'],
            ['456', 'MS', 'https://example.com/2', 'Example Two', 'Inactive'],
        ]
        result = parse_collection_jobs(values)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].collection_id, 123)
        self.assertEqual(result[0].repository, 'UA')
        self.assertEqual(result[0].row_number, 3)

    def test_header_variants(self):
        """
        Checks that header spacing variants are accepted.
        """
        values = [
            ['Header row follows'],
            ['Collection ID', 'Repository', 'Active / Inactive'],
            ['789', 'UA', 'Active'],
        ]
        result = parse_collection_jobs(values)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].collection_id, 789)


class TestCollectionReportingContract(TestCase):
    """
    Test cases for worksheet reporting-column validation and writes.
    """

    def test_validation_fails_when_reporting_column_is_missing(self):
        """
        Checks that reporting validation fails clearly when a required column is absent.
        """
        header_location = HeaderLocation(
            header_row_index=1,
            column_map={
                'collection_id': 0,
                'active_inactive': 1,
                'processing_status_main': 2,
                'summary_status_last_wasapi_check': 3,
                'summary_status_downloaded_warcs_count': 4,
                'summary_status_downloaded_warcs_size': 5,
                'summary_status_server_path': 6,
            },
        )

        with self.assertRaises(CollectionSheetContractError) as exc_context:
            validate_required_reporting_fields(header_location)

        self.assertIn('processing_status_detail', str(exc_context.exception))

    def test_start_status_write_uses_expected_row_and_payload(self):
        """
        Checks that start-status writes target the expected row and status columns.
        """
        worksheet = MagicMock()
        header_location = HeaderLocation(
            header_row_index=1,
            column_map={
                'processing_status_main': 4,
                'processing_status_detail': 5,
            },
        )
        status_update = CollectionProcessingStatusUpdate(
            processing_status_main='discovery-in-progress',
            processing_status_detail='store-time-after 2026-02-01T00:00:00+00:00',
        )

        update_collection_processing_status(worksheet, header_location, 7, status_update)

        self.assertEqual(
            worksheet.batch_update.call_args.args[0],
            [
                {'range': 'E7', 'values': [['discovery-in-progress']]},
                {'range': 'F7', 'values': [['store-time-after 2026-02-01T00:00:00+00:00']]},
            ],
        )

    def test_final_reporting_write_includes_status_and_summary_fields(self):
        """
        Checks that final reporting writes status and required summary fields together.
        """
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
        status_update = CollectionProcessingStatusUpdate(
            processing_status_main='downloaded-without-errors',
            processing_status_detail='1 file downloads completed successfully',
        )
        summary_update = CollectionSummaryUpdate(
            summary_status_last_wasapi_check='2026-03-07T15:00:00+00:00',
            summary_status_downloaded_warcs_count='1',
            summary_status_downloaded_warcs_size='11',
            summary_status_server_path='/tmp/storage/collections/123',
        )

        update_collection_final_reporting(worksheet, header_location, 9, status_update, summary_update)

        self.assertEqual(
            worksheet.batch_update.call_args.args[0],
            [
                {'range': 'A9', 'values': [['downloaded-without-errors']]},
                {'range': 'B9', 'values': [['1 file downloads completed successfully']]},
                {'range': 'C9', 'values': [['2026-03-07T15:00:00+00:00']]},
                {'range': 'D9', 'values': [['1']]},
                {'range': 'E9', 'values': [['11']]},
                {'range': 'F9', 'values': [['/tmp/storage/collections/123']]},
            ],
        )


if __name__ == '__main__':
    unittest.main()
