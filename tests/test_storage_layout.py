import sys
import unittest
from pathlib import Path
from unittest import TestCase

sys.path.append(str(Path(__file__).parent.parent))

from lib.storage_layout import (
    StorageLayoutError,
    build_fixity_paths,
    build_warc_destination_path,
    extract_warc_timestamp_parts,
    plan_collection_paths,
)


class TestExtractWarcTimestampParts(TestCase):
    """
    Test cases for WARC filename timestamp parsing.
    """

    def test_extracts_year_and_month_from_valid_warc_filename(self):
        """
        Checks that a valid WARC filename yields the expected year and month.
        """
        result = extract_warc_timestamp_parts('ARCHIVEIT-123-20260306123456-00000-example.warc.gz')
        self.assertEqual(result, ('2026', '03'))

    def test_raises_for_filename_without_parseable_timestamp(self):
        """
        Checks that an invalid filename raises a clear storage-layout error.
        """
        with self.assertRaises(StorageLayoutError):
            extract_warc_timestamp_parts('example.warc.gz')


class TestBuildPaths(TestCase):
    """
    Test cases for local WARC and fixity path building.
    """

    def test_builds_expected_warc_destination_path(self):
        """
        Checks that the WARC destination path matches the collection year/month layout.
        """
        storage_root = Path('/tmp/warc-storage')

        result = build_warc_destination_path(
            storage_root,
            123,
            'ARCHIVEIT-123-20260306123456-00000-example.warc.gz',
        )

        self.assertEqual(
            result,
            storage_root / 'collections' / '123' / 'warcs' / '2026' / '03' / 'ARCHIVEIT-123-20260306123456-00000-example.warc.gz',
        )

    def test_builds_expected_fixity_paths(self):
        """
        Checks that the fixity sidecar paths match the collection year/month layout.
        """
        storage_root = Path('/tmp/warc-storage')

        sha256_path, json_path = build_fixity_paths(
            storage_root,
            123,
            'ARCHIVEIT-123-20260306123456-00000-example.warc.gz',
        )

        expected_root = storage_root / 'collections' / '123' / 'fixity' / '2026' / '03'
        self.assertEqual(
            sha256_path,
            expected_root / 'ARCHIVEIT-123-20260306123456-00000-example.warc.gz.sha256',
        )
        self.assertEqual(
            json_path,
            expected_root / 'ARCHIVEIT-123-20260306123456-00000-example.warc.gz.json',
        )

    def test_plans_collection_paths_as_structured_result(self):
        """
        Checks that planned collection paths return the expected structured path data.
        """
        storage_root = Path('/tmp/warc-storage')

        result = plan_collection_paths(
            storage_root,
            123,
            'ARCHIVEIT-123-20260306123456-00000-example.warc.gz',
        )

        self.assertEqual(result.filename, 'ARCHIVEIT-123-20260306123456-00000-example.warc.gz')
        self.assertEqual(result.year, '2026')
        self.assertEqual(result.month, '03')
        self.assertEqual(
            result.warc_path,
            storage_root / 'collections' / '123' / 'warcs' / '2026' / '03' / 'ARCHIVEIT-123-20260306123456-00000-example.warc.gz',
        )


if __name__ == '__main__':
    unittest.main()
