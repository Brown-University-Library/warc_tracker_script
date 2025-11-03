import sys
import unittest
from pathlib import Path
from unittest import TestCase

sys.path.append(str(Path(__file__).parent.parent))  # add project directory to the Python path
from main import validate_collection_ids  # continue imports


class TestValidateCollectionIds(TestCase):
    """Test cases for the validate_collection_ids function."""

    def test_single_id(self):
        """Test with a single collection ID."""
        result = validate_collection_ids(['id123'])
        self.assertEqual(result, ['id123'])

    def test_multiple_ids(self):
        """Test with multiple space-separated collection IDs."""
        result = validate_collection_ids(['id1', 'id2', 'id3'])
        self.assertEqual(result, ['id1', 'id2', 'id3'])

    def test_comma_separated_ids(self):
        """Test with comma-separated collection IDs."""
        result = validate_collection_ids(['id1,id2,id3'])
        self.assertEqual(result, ['id1', 'id2', 'id3'])

    def test_mixed_separators(self):
        """Test with mixed space and comma separators."""
        result = validate_collection_ids(['id1,id2', 'id3,id4'])
        self.assertEqual(result, ['id1', 'id2', 'id3', 'id4'])

    def test_whitespace_handling(self):
        """Test handling of whitespace in input."""
        result = validate_collection_ids(['  id1  ', '  id2  ,  id3  '])
        self.assertEqual(result, ['id1', 'id2', 'id3'])

    def test_empty_strings(self):
        """Test that empty strings are filtered out."""
        result = validate_collection_ids(['id1', '', 'id2', '  ', 'id3'])
        self.assertEqual(result, ['id1', 'id2', 'id3'])

    def test_empty_input(self):
        """Test that empty input raises ValueError."""
        with self.assertRaises(ValueError):
            validate_collection_ids([])

    def test_none_input(self):
        """Test that None input raises ValueError."""
        with self.assertRaises(ValueError):
            validate_collection_ids(None)

    def test_all_empty_strings(self):
        """Test that input with only empty strings raises ValueError."""
        with self.assertRaises(ValueError):
            validate_collection_ids(['', '  ', '\t', '\n'])


if __name__ == '__main__':
    unittest.main()
