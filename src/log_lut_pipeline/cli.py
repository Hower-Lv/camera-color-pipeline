from __future__ import annotations

import argparse
import json

from .config import PipelineConfig
from .orchestrator import run_synthetic_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="log-lut-pipeline",
        description="Reconstruct a camera Log response and deploy a chart-validated LUT",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    synthetic = subparsers.add_parser("synthetic", help="run the data-free end-to-end example")
    synthetic.add_argument("--config", required=True)
    synthetic.add_argument("--output", required=True)
    args = parser.parse_args()

    config = PipelineConfig.from_toml(args.config)
    report = run_synthetic_pipeline(config, args.output, config_path=args.config)
    print(json.dumps(report, indent=2))
    if report["status"] != "pass":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
