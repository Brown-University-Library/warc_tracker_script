from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass(frozen=True)
class DownloadResult:
    """
    Represents the outcome of one attempted file download.
    """

    success: bool
    destination_path: Path
    partial_path: Path
    bytes_written: int
    source_url: str
    error_message: str | None


def build_partial_download_path(destination_path: Path) -> Path:
    """
    Builds the partial-download path for one final destination.
    """
    result = destination_path.with_name(f'{destination_path.name}.partial')
    return result


def download_to_path(
    client: httpx.Client,
    source_url: str,
    destination_path: Path,
    chunk_size: int = 65536,
) -> DownloadResult:
    """
    Streams one remote file to a local destination using a partial file and atomic rename.
    """
    partial_path = build_partial_download_path(destination_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if partial_path.exists():
        partial_path.unlink()

    bytes_written = 0
    try:
        with client.stream('GET', source_url) as response:
            response.raise_for_status()
            with partial_path.open('wb') as partial_file:
                for chunk in response.iter_bytes(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    partial_file.write(chunk)
                    bytes_written += len(chunk)
        partial_path.replace(destination_path)
        result = DownloadResult(
            success=True,
            destination_path=destination_path,
            partial_path=partial_path,
            bytes_written=bytes_written,
            source_url=source_url,
            error_message=None,
        )
    except Exception as exc:
        if partial_path.exists():
            partial_path.unlink()
        result = DownloadResult(
            success=False,
            destination_path=destination_path,
            partial_path=partial_path,
            bytes_written=bytes_written,
            source_url=source_url,
            error_message=str(exc),
        )
    return result
