import argparse
from argparse import Namespace


def validate_collection_ids(collection_input: list[str] | None) -> list[str]:
    """
    Validates and processes collection IDs from input.
    Called by handle_args().
    """
    if not collection_input:
        raise ValueError('No collection IDs provided')
    split_ids = []
    for id_string in collection_input:
        split_ids.extend(id_string.split(','))

    # Clean and validate the IDs
    cleaned_ids = [id_str.strip() for id_str in split_ids if id_str.strip()]

    if not cleaned_ids:
        raise ValueError('No valid collection IDs found after processing input')

    return cleaned_ids


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
        nargs='+',
        help='Space-separated list of collection IDs (can include comma-separated values)',
    )

    args = parser.parse_args()

    # Validate collection_ids if provided
    if hasattr(args, 'collection_ids') and args.collection_ids:
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
    print(f'Processing collection: {collection_id}')


def manage_tracker_check() -> None:
    """
    Main function to manage WARC tracker checks.

    Handles both single collection and multiple collections processing
    based on command line arguments.
    """
    args: Namespace = handle_args()

    if args.collection_id:
        print(f'Processing single collection: {args.collection_id}')
        check_collection(collection_id=args.collection_id)
    elif args.collection_ids:
        print(f'Processing multiple collections: {", ".join(args.collection_ids)}')
        for cid in args.collection_ids:
            check_collection(collection_id=cid)


if __name__ == '__main__':
    manage_tracker_check()
