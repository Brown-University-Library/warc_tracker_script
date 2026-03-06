import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.append(str(Path(__file__).parent.parent))

from lib.fixity import compute_sha256_for_file, write_fixity_sidecars


class TestComputeSha256ForFile(TestCase):
    """
    Test cases for SHA-256 computation.
    """

    def test_returns_expected_hexdigest_for_known_content(self):
        """
        Checks that known file content produces the expected SHA-256 digest.
        """
        content = b'alpha-beta-gamma'
        expected_digest = hashlib.sha256(content).hexdigest()

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / 'example.warc.gz'
            file_path.write_bytes(content)

            result = compute_sha256_for_file(file_path, chunk_size=4)

        self.assertEqual(result, expected_digest)


class TestWriteFixitySidecars(TestCase):
    """
    Test cases for fixity sidecar writing.
    """

    def test_writes_checksum_and_json_sidecars(self):
        """
        Checks that checksum and JSON sidecars are written with expected metadata.
        """
        content = b'warc-content-here'
        expected_digest = hashlib.sha256(content).hexdigest()
        source_url = 'https://example.org/file.warc.gz'

        with tempfile.TemporaryDirectory() as temp_dir:
            warc_path = Path(temp_dir) / 'warcs' / 'file.warc.gz'
            sha256_path = Path(temp_dir) / 'fixity' / 'file.warc.gz.sha256'
            json_path = Path(temp_dir) / 'fixity' / 'file.warc.gz.json'
            warc_path.parent.mkdir(parents=True, exist_ok=True)
            warc_path.write_bytes(content)

            result = write_fixity_sidecars(warc_path, sha256_path, json_path, source_url)

            self.assertTrue(result.success)
            self.assertEqual(result.sha256_hexdigest, expected_digest)
            self.assertEqual(result.size, len(content))
            self.assertEqual(sha256_path.read_text(encoding='utf-8'), f'{expected_digest} *file.warc.gz\n')
            json_data = json.loads(json_path.read_text(encoding='utf-8'))
            self.assertEqual(json_data['sha256'], expected_digest)
            self.assertEqual(json_data['size'], len(content))
            self.assertEqual(json_data['source_url'], source_url)
            self.assertEqual(json_data['warc_filename'], 'file.warc.gz')
            self.assertTrue(json_data['completed_at'])

    def test_returns_failure_and_leaves_warc_in_place_when_sidecar_write_fails(self):
        """
        Checks that sidecar-writing failure leaves the downloaded WARC file in place.
        """
        source_url = 'https://example.org/file.warc.gz'

        with tempfile.TemporaryDirectory() as temp_dir:
            warc_path = Path(temp_dir) / 'warcs' / 'file.warc.gz'
            sha256_path = Path(temp_dir) / 'fixity' / 'file.warc.gz.sha256'
            json_path = Path(temp_dir) / 'fixity' / 'file.warc.gz.json'
            warc_path.parent.mkdir(parents=True, exist_ok=True)
            warc_path.write_bytes(b'warc-content-here')

            with patch('lib.fixity.write_text_atomically', side_effect=OSError('disk full')):
                result = write_fixity_sidecars(warc_path, sha256_path, json_path, source_url)

            self.assertFalse(result.success)
            self.assertIn('disk full', result.error_message)
            self.assertTrue(warc_path.exists())
            self.assertFalse(sha256_path.exists())
            self.assertFalse(json_path.exists())


if __name__ == '__main__':
    unittest.main()
