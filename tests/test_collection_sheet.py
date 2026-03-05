import sys
import unittest
from pathlib import Path
from unittest import TestCase

sys.path.append(str(Path(__file__).parent.parent))

from lib.collection_sheet import parse_collection_id, parse_collection_jobs


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


if __name__ == '__main__':
    unittest.main()
