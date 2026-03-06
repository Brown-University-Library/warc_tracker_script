import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class FixityResult:
    """
    Represents the result of generating local fixity sidecars for one WARC file.
    """

    success: bool
    warc_path: Path
    sha256_path: Path
    json_path: Path
    sha256_hexdigest: str | None
    size: int
    source_url: str
    completed_at: str | None
    error_message: str | None


def compute_sha256_for_file(file_path: Path, chunk_size: int = 65536) -> str:
    """
    Computes the SHA-256 hex digest for one local file using chunked reads.
    Called by: write_fixity_sidecars()
    """
    hasher = hashlib.sha256()
    with file_path.open('rb') as file_handle:
        for chunk in iter(lambda: file_handle.read(chunk_size), b''):
            hasher.update(chunk)
    result = hasher.hexdigest()
    return result


def build_sidecar_partial_path(path: Path) -> Path:
    """
    Builds a temporary sidecar path for atomic sidecar writing.
    Called by: write_text_atomically()
    """
    result = path.with_name(f'{path.name}.partial')
    return result


def write_text_atomically(destination_path: Path, content: str) -> None:
    """
    Writes text content atomically to one destination path.
    Called by: write_fixity_sidecars()
    """
    partial_path = build_sidecar_partial_path(destination_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if partial_path.exists():
        partial_path.unlink()
    try:
        partial_path.write_text(content, encoding='utf-8')
        partial_path.replace(destination_path)
    except Exception:
        if partial_path.exists():
            partial_path.unlink()
        raise


def write_fixity_sidecars(
    warc_path: Path,
    sha256_path: Path,
    json_path: Path,
    source_url: str,
    chunk_size: int = 65536,
) -> FixityResult:
    """
    Computes SHA-256 and writes checksum and JSON sidecars for one downloaded WARC file.
    Called by: run_planned_downloads()
    """
    size = 0
    sha256_hexdigest: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    success = False
    try:
        size = warc_path.stat().st_size
        sha256_hexdigest = compute_sha256_for_file(warc_path, chunk_size=chunk_size)
        completed_at = datetime.now(UTC).isoformat()
        sha256_content = f'{sha256_hexdigest} *{warc_path.name}\n'
        json_content = json.dumps(
            {
                'sha256': sha256_hexdigest,
                'size': size,
                'source_url': source_url,
                'warc_filename': warc_path.name,
                'warc_path': str(warc_path),
                'sha256_path': str(sha256_path),
                'completed_at': completed_at,
            },
            indent=2,
            sort_keys=True,
        )
        write_text_atomically(sha256_path, sha256_content)
        write_text_atomically(json_path, f'{json_content}\n')
        success = True
    except Exception as exc:
        error_message = str(exc)
    result = FixityResult(
        success=success,
        warc_path=warc_path,
        sha256_path=sha256_path,
        json_path=json_path,
        sha256_hexdigest=sha256_hexdigest,
        size=size,
        source_url=source_url,
        completed_at=completed_at,
        error_message=error_message,
    )
    return result
