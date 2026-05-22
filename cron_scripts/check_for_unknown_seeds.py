import argparse
import json
import logging
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

import dotenv

dotenv.load_dotenv()

log = logging.getLogger(__name__)

UNKNOWN_SEED_FOLDER_NAME = 'UNKNOWN_SEED'
UNKNOWN_SEED_ALERT_RECIPIENTS_ENV = 'UNKNOWN_SEED_ALERT_RECIPIENTS'
DEFAULT_SMTP_HOST = 'localhost'
DEFAULT_SMTP_PORT = 25
DEFAULT_FROM_EMAIL = 'warc-tracker@localhost'


def configure_logging(log_level_name: str) -> None:
    """
    Configures console logging for the unknown-seed checker.
    Called by: main()
    """
    log_level = getattr(logging, log_level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format='[%(asctime)s] %(levelname)s [%(module)s-%(funcName)s()::%(lineno)d] %(message)s',
        datefmt='%d/%b/%Y %H:%M:%S',
    )


def parse_args() -> argparse.Namespace:
    """
    Parses command-line arguments.
    Called by: main()
    """
    parser = argparse.ArgumentParser(
        description='Scan WARC storage for files saved under UNKNOWN_SEED and send an alert when any are found.',
    )
    parser.add_argument(
        '--storage-root',
        default=os.getenv('WARC_STORAGE_ROOT'),
        help='WARC storage root. Defaults to WARC_STORAGE_ROOT from the environment.',
    )
    parser.add_argument(
        '--log-level',
        default=os.getenv('LOG_LEVEL', 'INFO'),
        help='Logging level. Defaults to LOG_LEVEL from the environment or INFO.',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Scan and report without sending email.',
    )
    result = parser.parse_args()
    return result


def resolve_storage_root(storage_root_value: str | None) -> Path:
    """
    Resolves the storage root path from CLI/environment input.
    Called by: main()
    """
    if storage_root_value is None or not storage_root_value.strip():
        raise ValueError('Missing storage root. Provide --storage-root or set WARC_STORAGE_ROOT.')
    result = Path(storage_root_value.strip()).expanduser()
    return result


def parse_alert_recipients(raw_value: str | None) -> list[tuple[str, str]]:
    """
    Parses alert recipients from JSON list pairs.
    Called by: main()
    """
    if raw_value is None or not raw_value.strip():
        raise ValueError(f'Missing {UNKNOWN_SEED_ALERT_RECIPIENTS_ENV} environment variable.')

    try:
        parsed_value = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError(f'{UNKNOWN_SEED_ALERT_RECIPIENTS_ENV} must be valid JSON.') from exc

    result: list[tuple[str, str]] = []
    if not isinstance(parsed_value, list):
        raise ValueError(f'{UNKNOWN_SEED_ALERT_RECIPIENTS_ENV} must be a JSON list.')

    for index, recipient_value in enumerate(parsed_value):
        if not isinstance(recipient_value, list | tuple) or len(recipient_value) != 2:
            raise ValueError(f'{UNKNOWN_SEED_ALERT_RECIPIENTS_ENV} item {index} must be a two-item list.')
        name_value, email_value = recipient_value
        if not isinstance(name_value, str) or not name_value.strip():
            raise ValueError(f'{UNKNOWN_SEED_ALERT_RECIPIENTS_ENV} item {index} has an invalid name.')
        if not isinstance(email_value, str) or not email_value.strip():
            raise ValueError(f'{UNKNOWN_SEED_ALERT_RECIPIENTS_ENV} item {index} has an invalid email address.')
        result.append((name_value.strip(), email_value.strip()))

    if not result:
        raise ValueError(f'{UNKNOWN_SEED_ALERT_RECIPIENTS_ENV} must include at least one recipient.')
    return result


def format_recipient_header(recipients: list[tuple[str, str]]) -> str:
    """
    Formats name/email pairs for an email header.
    Called by: build_unknown_seed_alert_message()
    """
    formatted_recipients = [f'{name} <{email_address}>' for name, email_address in recipients]
    result = ', '.join(formatted_recipients)
    return result


def scan_unknown_seed_paths(storage_root: Path) -> list[Path]:
    """
    Scans storage for WARC files under UNKNOWN_SEED folders.
    Called by: main()
    """
    result: list[Path] = []
    if storage_root.exists():
        for unknown_seed_root in storage_root.glob(f'collections/*/{UNKNOWN_SEED_FOLDER_NAME}'):
            if unknown_seed_root.is_dir():
                result.extend(path for path in unknown_seed_root.rglob('*.warc.gz') if path.is_file())
    result.sort()
    return result


def build_unknown_seed_alert_body(storage_root: Path, unknown_seed_paths: list[Path]) -> str:
    """
    Builds the plain-text unknown-seed alert body.
    Called by: build_unknown_seed_alert_message()
    """
    relative_paths: list[str] = []
    for path in unknown_seed_paths:
        try:
            relative_paths.append(str(path.relative_to(storage_root)))
        except ValueError:
            relative_paths.append(str(path))
    joined_paths = '\n'.join(f'- {path}' for path in relative_paths)
    result = (
        f'WARC tracker found {len(unknown_seed_paths)} WARC file(s) under UNKNOWN_SEED.\n\n'
        f'Storage root: {storage_root}\n\n'
        f'{joined_paths}\n'
    )
    return result


def build_unknown_seed_alert_message(
    storage_root: Path,
    unknown_seed_paths: list[Path],
    recipients: list[tuple[str, str]],
) -> EmailMessage:
    """
    Builds the unknown-seed alert email message.
    Called by: send_unknown_seed_alert()
    """
    from_email = os.getenv('UNKNOWN_SEED_ALERT_FROM_EMAIL', DEFAULT_FROM_EMAIL)
    subject = os.getenv('UNKNOWN_SEED_ALERT_SUBJECT', 'WARC tracker UNKNOWN_SEED files found')
    message = EmailMessage()
    message['From'] = from_email
    message['To'] = format_recipient_header(recipients)
    message['Subject'] = subject
    message.set_content(build_unknown_seed_alert_body(storage_root, unknown_seed_paths))
    result = message
    return result


def send_unknown_seed_alert(
    storage_root: Path,
    unknown_seed_paths: list[Path],
    recipients: list[tuple[str, str]],
) -> None:
    """
    Sends an unknown-seed alert email through SMTP.
    Called by: main()
    """
    smtp_host = os.getenv('UNKNOWN_SEED_ALERT_SMTP_HOST', DEFAULT_SMTP_HOST)
    smtp_port = int(os.getenv('UNKNOWN_SEED_ALERT_SMTP_PORT', str(DEFAULT_SMTP_PORT)))
    message = build_unknown_seed_alert_message(storage_root, unknown_seed_paths, recipients)
    recipient_addresses = [email_address for _name, email_address in recipients]
    with smtplib.SMTP(smtp_host, smtp_port) as smtp:
        smtp.send_message(message, to_addrs=recipient_addresses)


def main() -> None:
    """
    Orchestrates the unknown-seed scan and alert.
    Called by: __main__
    """
    args = parse_args()
    configure_logging(args.log_level)
    try:
        storage_root = resolve_storage_root(args.storage_root)
        unknown_seed_paths = scan_unknown_seed_paths(storage_root)
        log.info('Found %s WARC files under UNKNOWN_SEED.', len(unknown_seed_paths))
        if unknown_seed_paths and args.dry_run:
            print(build_unknown_seed_alert_body(storage_root, unknown_seed_paths))
        elif unknown_seed_paths:
            recipients = parse_alert_recipients(os.getenv(UNKNOWN_SEED_ALERT_RECIPIENTS_ENV))
            send_unknown_seed_alert(storage_root, unknown_seed_paths, recipients)
            log.info('Sent UNKNOWN_SEED alert to %s recipients.', len(recipients))
        else:
            log.info('No UNKNOWN_SEED alert needed.')
    except Exception as exc:
        log.exception('UNKNOWN_SEED check failed.')
        print(f'UNKNOWN_SEED check failed: {exc}', file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == '__main__':
    main()
