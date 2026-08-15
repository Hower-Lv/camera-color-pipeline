from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np


def _load_targets(path: Path) -> tuple[list[str], np.ndarray]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("target CSV is empty")
    names = [
        row.get("name") or row.get("patch_name") or f"Patch {index + 1:02d}"
        for index, row in enumerate(rows)
    ]
    xyz = np.asarray(
        [
            [
                float(row.get("x") or row.get("target_x")),
                float(row.get("y") or row.get("target_y")),
                float(row.get("z") or row.get("target_z")),
            ]
            for row in rows
        ],
        dtype=np.float64,
    )
    return names, xyz


def run_lut_gallery(
    image_path: str | Path,
    lut_dir: str | Path,
    corners_path: str | Path,
    targets_path: str | Path,
    output_dir: str | Path,
    *,
    source_encoding: str = "D-Log M",
) -> dict[str, Path]:
    try:
        from log_reconstruction import evaluate_lut_gallery, infer_lut_profile
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Install the full project dependencies before running the LUT gallery"
        ) from exc

    source = Path(image_path)
    directory = Path(lut_dir)
    corners_file = Path(corners_path)
    target_file = Path(targets_path)
    image = np.asarray(Image.open(source).convert("RGB"), dtype=np.float64) / 255.0
    corners = np.asarray(
        json.loads(corners_file.read_text(encoding="utf-8-sig")), dtype=np.float64
    )
    names, targets = _load_targets(target_file)
    profiles = [infer_lut_profile(path) for path in sorted(directory.rglob("*.cube"))]
    if not profiles:
        raise ValueError(f"no .cube files found under {directory}")
    return evaluate_lut_gallery(
        image,
        profiles,
        corners,
        targets,
        output_dir,
        source_encoding=source_encoding,
        patch_names=names,
    )
