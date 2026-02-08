import logging
import os

from lib.collection_sheet import parse_collection_id

log = logging.getLogger(__name__)


def validate_collection_ids(collection_id_string: str | None) -> list[str]:
    """
    Validates collection id input and returns a list of ids.
    """
    if collection_id_string is None:
        raise ValueError('Collection IDs cannot be None.')

    cleaned_input = collection_id_string.strip()
    if not cleaned_input:
        raise ValueError('Collection IDs cannot be empty.')

    if ',' in cleaned_input:
        candidate_ids = [candidate.strip() for candidate in cleaned_input.split(',')]
        if any(not candidate for candidate in candidate_ids):
            raise ValueError('Collection IDs cannot include empty values.')
        if any(' ' in candidate for candidate in candidate_ids):
            raise ValueError('Collection IDs cannot mix commas and spaces as separators.')
        result = candidate_ids
    else:
        result = [cleaned_input]

    return result


def load_collection_id_filter() -> set[int] | None:
    """
    Loads optional collection id filter from the environment.
    """
    collection_id_string = os.getenv('COLLECTION_ID_FILTER')
    if collection_id_string is None:
        return None

    validated_ids = validate_collection_ids(collection_id_string)
    collection_ids: set[int] = set()
    for collection_id_value in validated_ids:
        parsed_id = parse_collection_id(collection_id_value)
        if parsed_id is None:
            log.error('Invalid collection id in COLLECTION_ID_FILTER: %s', collection_id_value)
            return None
        collection_ids.add(parsed_id)

    if not collection_ids:
        return None

    return collection_ids
