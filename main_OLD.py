import argparse
import json
import logging
import os
from argparse import Namespace

import dotenv

dotenv.load_dotenv()


## settings ---------------------------------------------------------
GSHEET_CREDENTIALS: dict = json.loads(os.environ['GSHEET_CREDENTIALS_JSON'])
LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO').upper()


## setup logging
log_level = getattr(logging, LOG_LEVEL)  # maps the string name to the corresponding logging level constant
logging.basicConfig(
    level=log_level,
    format='[%(asctime)s] %(levelname)s [%(module)s-%(funcName)s()::%(lineno)d] %(message)s',
    datefmt='%d/%b/%Y %H:%M:%S',
)
log = logging.getLogger(__name__)


def validate_collection_ids(collection_input: str) -> list[str]:
    """
    Validates and processes collection IDs from input.
    Called by handle_args().
    """
    log.debug(f'collection_input: {collection_input}')
    if not collection_input or not collection_input.strip():
        log.debug('nopePreA')
        raise ValueError('No collection IDs provided')

    input_str = collection_input.strip()
    log.debug(f'input_str: {input_str}')

    # If commas are present, treat commas as the only valid separators.
    # Spaces around commas are allowed, but spaces used as separators in
    # addition to commas are not allowed (e.g., "id1,id2 id3").
    if ',' in input_str:
        parts = [part.strip() for part in input_str.split(',')]
        log.debug(f'parts: {parts}')
        # If any part still contains a space, then spaces were used as separators
        # in addition to commas; that's invalid mixed separators.
        if any(' ' in part for part in parts if part):
            log.debug('nopeA')
            raise ValueError('Use either spaces or commas to separate IDs, not both')
        cleaned_ids = [part for part in parts if part]
        if not cleaned_ids:
            log.debug('nopeB')
            raise ValueError('No valid collection IDs found after processing input')
        return cleaned_ids

    # No commas: treat the entire input as a single ID (even if it contains spaces)
    return [input_str]


def handle_args() -> Namespace:
    """
    Parses and returns command line arguments.
    Called by manage_tracker_check().
    """
    parser = argparse.ArgumentParser(description='Manage WARC tracker checks.')

    # Add mutually exclusive group for collection_id and collection_ids
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--collection_id', type=str, help='Single collection ID to process')
    group.add_argument(
        '--collection_ids',
        type=str,
        help='Comma-separated list of collection IDs',
    )

    args = parser.parse_args()

    # Validate collection_ids if provided
    if hasattr(args, 'collection_ids') and args.collection_ids:
        log.debug(f'args.collection_ids in handle_args(): ``{args.collection_ids}``')
        try:
            args.collection_ids = validate_collection_ids(args.collection_ids)
        except ValueError as e:
            parser.error(f'--collection_ids: {str(e)}')

    return args


def check_collection(collection_id: str) -> None:
    """
    Processes a single collection ID.
    Called by manage_tracker_check().
    """
    log.info(f'Processing collection: {collection_id}')


def manage_tracker_check() -> None:
    """
    Main function to manage WARC tracker checks.

    Handles both single collection and multiple collections processing
    based on command line arguments.
    """
    args: Namespace = handle_args()

    if args.collection_id:
        log.debug(f'Processing single collection: {args.collection_id}')
        check_collection(args.collection_id)
    elif args.collection_ids:
        log.debug(f'args.collection_ids in manage_tracker_check(): ``{args.collection_ids}``')
        log.debug(f'Processing multiple collections: {", ".join(args.collection_ids)}')
        for cid in args.collection_ids:
            check_collection(cid)

    log.debug(f'project_id, ``{GSHEET_CREDENTIALS["project_id"]}``')
    log.debug(f'service-account-email, ``{GSHEET_CREDENTIALS["client_email"]}``')
    return None


if __name__ == '__main__':
    manage_tracker_check()
