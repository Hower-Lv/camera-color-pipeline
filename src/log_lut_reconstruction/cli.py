from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from .config import PipelineConfig
from .log_templates import PUBLIC_LOG_TEMPLATES, compare_public_log_templates
from .lut_gallery import run_lut_gallery
from .measurement_policy import MeasurementKind, apply_selective_measurement_policy


def _read_template_samples(
    path: Path,
) -> tuple[np.ndarray, np.ndarray, list[str] | None, list[str], np.ndarray]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("sample CSV is empty")
    linear = np.asarray([float(row["linear"]) for row in rows], dtype=np.float64)
    encoded = np.asarray([float(row["encoded"]) for row in rows], dtype=np.float64)
    groups = None
    if all(row.get("capture_id") not in {None, ""} for row in rows):
        groups = [str(row["capture_id"]) for row in rows]
    kinds = [
        str(row.get("measurement_kind") or MeasurementKind.PAIRED_TRANSFER.value)
        for row in rows
    ]
    spatial_factors = np.asarray(
        [float(row.get("spatial_factor") or 1.0) for row in rows], dtype=np.float64
    )
    return linear, encoded, groups, kinds, spatial_factors


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="log-lut-reconstruction",
        description="Reconstruct a camera Log response and deploy a chart-validated LUT",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    synthetic = subparsers.add_parser("synthetic", help="run the data-free end-to-end example")
    synthetic.add_argument("--config", required=True)
    synthetic.add_argument("--output", required=True)
    templates = subparsers.add_parser(
        "compare-templates",
        help="fit published Log shape templates to paired relative-linear samples",
    )
    templates.add_argument("--samples", type=Path, required=True)
    templates.add_argument("--output", type=Path, required=True)
    templates.add_argument(
        "--template",
        action="append",
        choices=sorted(PUBLIC_LOG_TEMPLATES),
        dest="templates",
    )
    templates.add_argument("--fit-offset", action="store_true")
    gallery = subparsers.add_parser(
        "lut-gallery",
        help="apply local .cube LUTs to one chart image and compare DeltaE00",
    )
    gallery.add_argument("--image", type=Path, required=True)
    gallery.add_argument("--lut-dir", type=Path, required=True)
    gallery.add_argument("--corners", type=Path, required=True)
    gallery.add_argument("--targets", type=Path, required=True)
    gallery.add_argument("--output", type=Path, required=True)
    gallery.add_argument("--source-encoding", default="D-Log M")
    args = parser.parse_args()

    if args.command == "synthetic":
        from .orchestrator import run_synthetic_pipeline

        config = PipelineConfig.from_toml(args.config)
        report = run_synthetic_pipeline(config, args.output, config_path=args.config)
        print(json.dumps(report, indent=2))
        if report["status"] != "pass":
            raise SystemExit(2)
        return
    if args.command == "compare-templates":
        linear, encoded, groups, kinds, spatial_factors = _read_template_samples(args.samples)
        policy_result = apply_selective_measurement_policy(
            linear,
            encoded,
            kinds,
            spatial_factors=spatial_factors,
        )
        report = compare_public_log_templates(
            policy_result.linear,
            policy_result.encoded,
            template_keys=args.templates,
            group_ids=groups,
            fit_offset=args.fit_offset,
        )
        report["measurement_policy"] = policy_result.summary()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return
    result = run_lut_gallery(
        args.image,
        args.lut_dir,
        args.corners,
        args.targets,
        args.output,
        source_encoding=args.source_encoding,
    )
    for key, path in result.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
