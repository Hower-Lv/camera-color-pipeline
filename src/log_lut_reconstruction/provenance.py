from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_record(path: str | Path, root: str | Path) -> dict[str, object]:
    file_path = Path(path)
    return {
        "path": file_path.resolve().relative_to(Path(root).resolve()).as_posix(),
        "bytes": file_path.stat().st_size,
        "sha256": sha256_file(file_path),
    }


def write_provenance_manifest(
    path: str | Path,
    *,
    root: str | Path,
    inputs: Iterable[str | Path],
    artifacts: Iterable[str | Path],
    metadata: dict[str, object],
) -> None:
    output = {
        "schema_version": 1,
        "metadata": metadata,
        "inputs": [artifact_record(item, root) for item in inputs],
        "artifacts": [artifact_record(item, root) for item in artifacts],
    }
    Path(path).write_text(json.dumps(output, indent=2), encoding="utf-8")
