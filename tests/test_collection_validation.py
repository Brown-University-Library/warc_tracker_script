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
        result = validate_collection_ids('id123')
        self.assertEqual(result, ['id123'])

    def test_bad_multiple_ids(self):
        """Checks that with multiple space-separated collection IDs returns only a single string list-element."""
        result = validate_collection_ids('id1 id2 id3')
        self.assertEqual(result, ['id1 id2 id3'])

    def test_good_comma_separated_ids(self):
        """Checks that with comma-separated collection IDs returns a list of strings."""
        result = validate_collection_ids('id1,id2,id3')
        self.assertEqual(result, ['id1', 'id2', 'id3'])

    def test_mixed_separators(self):
        """Checks that mixed space and comma separators returns a value-error."""
        with self.assertRaises(ValueError):
            validate_collection_ids('id1,id2 id3')

    def test_whitespace_handling(self):
        """Checks handling of whitespace around commas in input."""
        result = validate_collection_ids('id1,  id2  ,id3')
        self.assertEqual(result, ['id1', 'id2', 'id3'])

    def test_empty_strings(self):
        """Checks that empty strings raise a value-error."""
        with self.assertRaises(ValueError):
            validate_collection_ids(' ')

    def test_empty_input(self):
        """Test that empty input raises ValueError."""
        with self.assertRaises(ValueError):
            validate_collection_ids('')

    def test_none_input(self):
        """Test that None input raises ValueError."""
        with self.assertRaises(ValueError):
            validate_collection_ids(None)

    def test_all_empty_strings(self):
        """Test that input with only empty non-value strings raises ValueError."""
        with self.assertRaises(ValueError):
            validate_collection_ids('\t')


if __name__ == '__main__':
    unittest.main()
