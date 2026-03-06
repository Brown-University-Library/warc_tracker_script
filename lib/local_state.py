import json
from pathlib import Path
from tempfile import NamedTemporaryFile

REQUIRED_TOP_LEVEL_DEFAULTS: dict[str, object] = {
    'enumeration_checkpoint_store_time_max': None,
    'files': {},
}


class LocalStateError(RuntimeError):
    """
    Represents an invalid local collection state file.
    """


def build_collection_root_path(storage_root: Path, collection_id: int) -> Path:
    """
    Builds the collection root path under the configured storage root.
    """
    result = storage_root / 'collections' / str(collection_id)
    return result


def build_state_file_path(storage_root: Path, collection_id: int) -> Path:
    """
    Builds the state.json path for one collection.
    """
    collection_root_path = build_collection_root_path(storage_root, collection_id)
    result = collection_root_path / 'state.json'
    return result


def make_default_collection_state() -> dict[str, object]:
    """
    Builds the default in-memory collection state structure.
    """
    result = {
        'enumeration_checkpoint_store_time_max': None,
        'files': {},
    }
    return result


def normalize_collection_state(state: dict[str, object]) -> dict[str, object]:
    """
    Normalizes a loaded collection state and fills missing required keys.
    """
    result = dict(state)
    for key, default_value in REQUIRED_TOP_LEVEL_DEFAULTS.items():
        if key not in result:
            if isinstance(default_value, dict):
                result[key] = dict(default_value)
            else:
                result[key] = default_value

    files_value = result.get('files')
    if not isinstance(files_value, dict):
        raise LocalStateError('Collection state field `files` must be a JSON object.')
    return result


def load_collection_state(storage_root: Path, collection_id: int) -> dict[str, object]:
    """
    Loads collection state from disk or returns the default state when absent.
    """
    state_file_path = build_state_file_path(storage_root, collection_id)
    if not state_file_path.exists():
        result = make_default_collection_state()
    else:
        try:
            payload = json.loads(state_file_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            raise LocalStateError(f'Malformed collection state JSON in {state_file_path}.') from exc
        if not isinstance(payload, dict):
            raise LocalStateError(f'Collection state file {state_file_path} must contain a JSON object.')
        result = normalize_collection_state(payload)
    return result


def save_collection_state(storage_root: Path, collection_id: int, state: dict[str, object]) -> Path:
    """
    Saves collection state to disk using an atomic replace.
    """
    normalized_state = normalize_collection_state(state)
    state_file_path = build_state_file_path(storage_root, collection_id)
    state_file_path.parent.mkdir(parents=True, exist_ok=True)

    with NamedTemporaryFile('w', encoding='utf-8', dir=state_file_path.parent, delete=False) as temp_file:
        json.dump(normalized_state, temp_file, indent=2, sort_keys=True)
        temp_file.write('\n')
        temp_file_path = Path(temp_file.name)

    temp_file_path.replace(state_file_path)
    result = state_file_path
    return result
