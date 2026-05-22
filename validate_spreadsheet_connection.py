import argparse
import os
import sys

import dotenv

from lib.collection_sheet import CollectionSheetContext, validate_collection_sheet_connection

dotenv.load_dotenv()


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
    else:
        env_spreadsheet_id = os.getenv('GSHEET_SPREADSHEET_ID')
        if env_spreadsheet_id is not None and env_spreadsheet_id.strip():
            result = env_spreadsheet_id.strip()
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


def run_validation(spreadsheet_id: str) -> int:
    """
    Runs spreadsheet connection validation and returns a process exit code.
    Called by: main()
    """
    exit_code = 1
    try:
        sheet_context = validate_collection_sheet_connection(spreadsheet_id)
    except Exception as exc:
        print(f'Spreadsheet connection validation failed: {exc}', file=sys.stderr)
    else:
        print(format_success_message(sheet_context))
        exit_code = 0
    return exit_code


def main() -> None:
    """
    Orchestrates argument parsing and spreadsheet validation.
    Called by: __main__
    """
    args = parse_args()
    try:
        spreadsheet_id = resolve_spreadsheet_id(args.spreadsheet_id)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    exit_code = run_validation(spreadsheet_id)
    raise SystemExit(exit_code)


if __name__ == '__main__':
    main()
