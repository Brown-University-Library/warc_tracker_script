import re
from dataclasses import dataclass
from pathlib import Path

from lib.local_state import build_collection_root_path

WARC_FILENAME_TIMESTAMP_PATTERN = re.compile(r'-(\d{4})(\d{2})\d{2}\d{6}(?:\d+)?-')


class StorageLayoutError(ValueError):
    """
    Represents an invalid filename or storage-layout input.
    """


@dataclass(frozen=True)
class PlannedCollectionPaths:
    """
    Represents planned local paths for one discovered WARC record.
    """

    filename: str
    warc_path: Path
    sha256_path: Path
    json_path: Path
    year: str
    month: str


def extract_warc_timestamp_parts(filename: str) -> tuple[str, str]:
    """
    Extracts the year and month partitions from a WARC filename timestamp.
    Called by: build_warc_destination_path()
    """
    normalized_filename = filename.strip()
    if not normalized_filename:
        raise StorageLayoutError('WARC filename must not be blank.')
    match = WARC_FILENAME_TIMESTAMP_PATTERN.search(normalized_filename)
    if match is None:
        raise StorageLayoutError(f'Could not extract year/month timestamp parts from filename: {filename}')
    result = (match.group(1), match.group(2))
    return result


def build_collection_storage_root(storage_root: Path, collection_id: int) -> Path:
    """
    Builds the collection root path for downloaded WARC content.
    Called by: build_warc_destination_path()
    """
    result = build_collection_root_path(storage_root, collection_id)
    return result


def build_warc_destination_path(storage_root: Path, collection_id: int, filename: str) -> Path:
    """
    Builds the destination path for one WARC file.
    Called by: plan_collection_paths()
    """
    year, month = extract_warc_timestamp_parts(filename)
    collection_root = build_collection_storage_root(storage_root, collection_id)
    result = collection_root / 'warcs' / year / month / filename
    return result


def build_fixity_paths(storage_root: Path, collection_id: int, filename: str) -> tuple[Path, Path]:
    """
    Builds the fixity sidecar paths for one WARC file.
    Called by: plan_collection_paths()
    """
    year, month = extract_warc_timestamp_parts(filename)
    collection_root = build_collection_storage_root(storage_root, collection_id)
    fixity_root = collection_root / 'fixity' / year / month
    result = (fixity_root / f'{filename}.sha256', fixity_root / f'{filename}.json')
    return result


def plan_collection_paths(storage_root: Path, collection_id: int, filename: str) -> PlannedCollectionPaths:
    """
    Builds the planned local WARC and fixity paths for one filename.
    Called by: build_planned_download_paths()
    """
    year, month = extract_warc_timestamp_parts(filename)
    warc_path = build_warc_destination_path(storage_root, collection_id, filename)
    sha256_path, json_path = build_fixity_paths(storage_root, collection_id, filename)
    result = PlannedCollectionPaths(
        filename=filename,
        warc_path=warc_path,
        sha256_path=sha256_path,
        json_path=json_path,
        year=year,
        month=month,
    )
    return result
