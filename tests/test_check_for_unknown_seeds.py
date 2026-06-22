import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).parent.parent))

from cron_scripts.check_for_unknown_seeds import (
    parse_alert_recipients,
    scan_unknown_seed_paths,
    send_unknown_seed_alert,
)


class TestParseAlertRecipients(TestCase):
    """
    Test cases for parsing UNKNOWN_SEED alert recipients.
    """

    def test_parses_json_name_email_pairs(self) -> None:
        """
        Checks that JSON list pairs become recipient tuples.
        """
        result = parse_alert_recipients('[["Birkin", "birkin@example.edu"], ["Archive Team", "team@example.edu"]]')

        self.assertEqual(result, [('Birkin', 'birkin@example.edu'), ('Archive Team', 'team@example.edu')])

    def test_rejects_flat_email_list(self) -> None:
        """
        Checks that flat email lists are rejected because names are required.
        """
        with self.assertRaises(ValueError):
            parse_alert_recipients('["birkin@example.edu"]')


class TestScanUnknownSeedPaths(TestCase):
    """
    Test cases for finding UNKNOWN_SEED files.
    """

    def test_scans_unknown_seed_warc_files(self) -> None:
        """
        Checks that WARC files under UNKNOWN_SEED folders are returned.
        """
        with TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            unknown_seed_warc = (
                storage_root
                / 'collections'
                / '11926'
                / 'UNKNOWN_SEED'
                / '2026'
                / '05'
                / 'example.warc.gz'
            )
            normal_seed_warc = (
                storage_root
                / 'collections'
                / '11926'
                / 'SEED123'
                / '2026'
                / '05'
                / 'example.warc.gz'
            )
            unknown_seed_warc.parent.mkdir(parents=True)
            normal_seed_warc.parent.mkdir(parents=True)
            unknown_seed_warc.write_bytes(b'unknown')
            normal_seed_warc.write_bytes(b'normal')

            result = scan_unknown_seed_paths(storage_root)

        self.assertEqual(result, [unknown_seed_warc])


class TestSendUnknownSeedAlert(TestCase):
    """
    Test cases for UNKNOWN_SEED alert email sending.
    """

    def test_sends_message_to_recipient_addresses(self) -> None:
        """
        Checks that SMTP receives an alert addressed to parsed recipient emails.
        """
        storage_root = Path('/tmp/storage')
        unknown_seed_path = storage_root / 'collections' / '11926' / 'UNKNOWN_SEED' / '2026' / '05' / 'example.warc.gz'
        smtp_instance = MagicMock()
        smtp_context = MagicMock()
        smtp_context.__enter__.return_value = smtp_instance

        with patch('cron_scripts.check_for_unknown_seeds.smtplib.SMTP', return_value=smtp_context) as mock_smtp:
            send_unknown_seed_alert(
                storage_root,
                [unknown_seed_path],
                [('Birkin', 'birkin@example.edu'), ('Archive Team', 'team@example.edu')],
            )

        self.assertEqual(mock_smtp.call_args.args, ('localhost', 25))
        self.assertEqual(smtp_instance.send_message.call_args.kwargs['to_addrs'], ['birkin@example.edu', 'team@example.edu'])


if __name__ == '__main__':
    unittest.main()
