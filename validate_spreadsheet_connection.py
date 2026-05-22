import argparse
import logging
import os
import sys

import dotenv

from lib.collection_sheet import (
    CollectionSheetContext,
    CollectionSheetContractError,
    validate_collection_sheet_connection,
)

dotenv.load_dotenv()

log = logging.getLogger(__name__)


def configure_logging(log_level_name: str) -> None:
    """
    Configures console logging for the validation script.
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
        description='Validate that a WARC tracker spreadsheet can be opened, parsed, and edited.',
    )
    parser.add_argument(
        '--spreadsheet-id',
        default=None,
        help='Google spreadsheet id to validate. Defaults to GSHEET_SPREADSHEET_ID from the environment.',
    )
    parser.add_argument(
        '--log-level',
        default=os.getenv('LOG_LEVEL', 'INFO'),
        help='Logging level. Defaults to LOG_LEVEL from the environment or INFO.',
    )
    result = parser.parse_args()
    return result


def resolve_spreadsheet_id(cli_spreadsheet_id: str | None) -> str:
    """
    Resolves the spreadsheet id from CLI arguments or the environment.
    Called by: main()
    """
    result = ''
    if cli_spreadsheet_id is not None and cli_spreadsheet_id.strip():
        result = cli_spreadsheet_id.strip()
        log.debug('Using spreadsheet id from --spreadsheet-id.')
    else:
        env_spreadsheet_id = os.getenv('GSHEET_SPREADSHEET_ID')
        if env_spreadsheet_id is not None and env_spreadsheet_id.strip():
            result = env_spreadsheet_id.strip()
            log.debug('Using spreadsheet id from GSHEET_SPREADSHEET_ID.')
    if not result:
        raise ValueError('Missing spreadsheet id. Provide --spreadsheet-id or set GSHEET_SPREADSHEET_ID.')
    return result


def format_success_message(sheet_context: CollectionSheetContext) -> str:
    """
    Formats the validation success message.
    Called by: run_validation()
    """
    result = (
        f'Spreadsheet connection validated for worksheet `{sheet_context.worksheet.title}` '
        f'with {len(sheet_context.collection_jobs)} active collection jobs.'
    )
    return result


def format_contract_error_message(exc: CollectionSheetContractError) -> str:
    """
    Formats a worksheet-contract validation failure message.
    Called by: run_validation()
    """
    result = (
        'Spreadsheet connection succeeded, but the worksheet is not ready in the expected format. '
        f'{exc}'
    )
    return result


def run_validation(spreadsheet_id: str) -> int:
    """
    Runs spreadsheet connection validation and returns a process exit code.
    Called by: main()
    """
    exit_code = 1
    log.info('Starting spreadsheet connection validation.')
    log.info('Attempting to open, parse, and edit spreadsheet id `%s`.', spreadsheet_id)
    try:
        sheet_context = validate_collection_sheet_connection(spreadsheet_id)
    except CollectionSheetContractError as exc:
        error_message = format_contract_error_message(exc)
        log.error(error_message)
        print(error_message, file=sys.stderr)
    except Exception as exc:
        log.exception('Spreadsheet connection validation failed.')
        print(f'Spreadsheet connection validation failed: {exc}', file=sys.stderr)
    else:
        success_message = format_success_message(sheet_context)
        log.info(success_message)
        print(success_message)
        exit_code = 0
    return exit_code


def main() -> None:
    """
    Orchestrates argument parsing and spreadsheet validation.
    Called by: __main__
    """
    args = parse_args()
    configure_logging(args.log_level)
    log.info('Loaded environment from .env if present.')
    try:
        spreadsheet_id = resolve_spreadsheet_id(args.spreadsheet_id)
    except ValueError as exc:
        log.exception('Unable to resolve spreadsheet id.')
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    exit_code = run_validation(spreadsheet_id)
    raise SystemExit(exit_code)


if __name__ == '__main__':
    main()
