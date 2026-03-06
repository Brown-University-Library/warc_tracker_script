import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import TestCase

sys.path.append(str(Path(__file__).parent.parent))

from tmp_inspect_collection_wasapi import build_metadata_summary, build_output_paths


class TestBuildOutputPaths(TestCase):
    """
    Test cases for output path construction.
    """

    def test_builds_timestamped_collection_paths(self):
        """
        Checks that output paths include the collection id and UTC timestamp.
        """
        output_dir = Path('/tmp/example-output')
        requested_at = datetime(2026, 3, 6, 12, 30, 45, tzinfo=UTC)

        result = build_output_paths(output_dir, 123, requested_at)

        expected_collection_dir = output_dir / 'collection_123' / '20260306T123045Z'
        self.assertEqual(result['collection_directory'], expected_collection_dir)
        self.assertEqual(result['pages_directory'], expected_collection_dir / 'pages')
        self.assertEqual(result['manifest_path'], expected_collection_dir / 'request_manifest.json')


class TestBuildMetadataSummary(TestCase):
    """
    Test cases for WASAPI metadata summarization.
    """

    def test_detects_duplicate_filenames_and_identifier_fields(self):
        """
        Checks that duplicate filenames and identifier-like fields are summarized.
        """
        pages = [
            {
                'results': [
                    {'filename': 'alpha.warc.gz', 'identifier': 'item-1'},
                    {'filename': 'alpha.warc.gz', 'crawl_id': 'crawl-2'},
                    {'filename': 'beta.warc.gz'},
                ],
            },
        ]

        result = build_metadata_summary(pages)

        self.assertEqual(result['total_pages_saved'], 1)
        self.assertEqual(result['total_records_observed'], 3)
        self.assertEqual(result['duplicate_filenames'], ['alpha.warc.gz'])
        self.assertEqual(result['duplicate_filename_count'], 1)
        self.assertEqual(result['records_with_identifier_like_fields'], 2)
        self.assertEqual(result['identifier_field_names_observed'], ['crawl_id', 'identifier'])
        self.assertEqual(result['flat_layout_assessment'], 'obviously_unsafe')

    def test_detects_filename_anomalies(self):
        """
        Checks that suspicious filenames are surfaced in anomaly examples.
        """
        pages = [
            {
                'results': [
                    {'filename': ' nested/file.warc.gz '},
                ],
            },
        ]

        result = build_metadata_summary(pages)

        self.assertEqual(result['duplicate_filename_count'], 0)
        self.assertEqual(len(result['filename_anomaly_examples']), 1)
        self.assertEqual(
            result['filename_anomaly_examples'][0]['anomalies'],
            ['contains_path_unsafe_character', 'leading_or_trailing_whitespace'],
        )
        self.assertEqual(result['flat_layout_assessment'], 'still_unclear')


if __name__ == '__main__':
    unittest.main()
