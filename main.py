import argparse


def handle_args():
    """Parse and return command line arguments."""
    parser = argparse.ArgumentParser(description='Manage WARC tracker checks.')

    # Add mutually exclusive group for collection_id and collection_ids
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--collection_id', type=str, help='Single collection ID to process')
    group.add_argument('--collection_ids', type=str, nargs='+', help='List of collection IDs to process')

    args = parser.parse_args()
    return args


def check_collection(collection_id: str):
    """Handle the tracker check for a single collection ID."""
    print(f'Processing collection: {collection_id}')


def manage_tracker_check():
    args = handle_args()

    if args.collection_id:
        print(f'Processing single collection: {args.collection_id}')
        # Call your manage_tracker_check function with single ID
        check_collection(collection_id=args.collection_id)
    elif args.collection_ids:
        print(f'Processing multiple collections: {", ".join(args.collection_ids)}')
        for cid in args.collection_ids:
            # Call your manage_tracker_check function for each ID
            check_collection(collection_id=cid)


if __name__ == '__main__':
    manage_tracker_check()
